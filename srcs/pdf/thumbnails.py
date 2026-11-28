#!/usr/bin/env python
# -*- coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4

# eBookOnline - A web portal to access your ebooks collection
# Copyright (C) 2021 Yannick Gicquel
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import logging
import os
import math
import queue
import signal
import shutil
import subprocess
import tempfile

import multiprocessing

from pypdf import PdfReader, PdfWriter

from wand.image import Image

from srcs.common.files import remove_quietly
from srcs.common.logs import setup_logging

log = logging.getLogger(__name__)

# Signals whose handlers are set by the gunicorn worker (graceful exit on
# SIGTERM, ...)
_INHERITED_SIGNALS = ("SIGTERM", "SIGQUIT", "SIGHUP", "SIGUSR1", "SIGUSR2",
                      "SIGWINCH", "SIGABRT")


def _reset_signal_handlers():
    """
    In a process forked from the server: the default signal handlers.
    Otherwise a process forked from a gunicorn worker keeps its handlers:
    SIGTERM, sent to the daemon processes by multiprocessing when the worker
    exits, would only ask for a graceful exit which never comes, and the
    worker would wait for it until killed by gunicorn (graceful timeout).
    """
    for name in _INHERITED_SIGNALS:
        signal.signal(getattr(signal, name), signal.SIG_DFL)
    # KeyboardInterrupt: stops the loop of the process (see __del__)
    signal.signal(signal.SIGINT, signal.default_int_handler)


# Backends of the thumbnails, tried in this order when none is chosen: the
# first one which makes an image (see Cache.__pdf2jpeg())
BACKENDS = ("pypdf-wand", "wand", "ghostscript")


def available_backends():
    """ The backends which can run here: Ghostscript when gs is installed """
    return [b for b in BACKENDS if b != "ghostscript" or shutil.which("gs")]


# Ghostscript fallback: largest image before the resize (the resolution is
# halved until below), longest run of gs
GS_MAX_IMAGE_BYTES = 2048 * 1024
GS_TIMEOUT = 120


# Start Of Frame markers of a JPEG file: they give its size (not DHT, JPG,
# DAC, whose codes are in the range)
_JPEG_SOF = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def jpeg_size(filename):
    """ (width, height) of a JPEG file, None when it is not a JPEG file """
    info = jpeg_info(filename)
    return info[:2] if info else None


def jpeg_info(filename):
    """
    (width, height, components) of a JPEG file, read from its header, None
    when it is not a JPEG file. components: 1 (gray), 3 (RGB), 4 (CMYK).
    Pure Python: ImageMagick would start its threads in the server process.
    """
    try:
        with open(filename, "rb") as f:
            if f.read(2) != b"\xff\xd8":
                return None
            while True:
                marker = f.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    return None
                code = marker[1]
                if code == 0xFF:
                    f.seek(-1, os.SEEK_CUR)  # fill byte
                    continue
                if code in (0x01, *range(0xD0, 0xD8)):
                    continue  # markers without length
                length = int.from_bytes(f.read(2), "big")
                if length < 2:
                    return None
                if code in _JPEG_SOF:
                    data = f.read(6)
                    if len(data) < 6:
                        return None
                    return (int.from_bytes(data[3:5], "big"), int.from_bytes(data[1:3], "big"),
                            data[5])
                f.seek(length - 2, os.SEEK_CUR)
    except OSError:
        return None


class Cache:

    instance = None
    file_list = []
    # False when the cache directory can not be written (see srcs.common.access):
    # no thumbnail is generated.
    writable = True

    @classmethod
    def get_instance(cls, *args, **kwargs):
        if cls.instance == None:
            log.debug("Cache instance: %s %s", args, kwargs)
            cls.instance = cls(*args, **kwargs)
        return cls.instance

    def __init__(self, cachedir, workers=None):
        """
        workers: number of thumbnail processes (requests of
        create_thumbnail()), the number of processors - 1 by default; 0 for
        none, e.g. for make_thumbnail() only (command line).
        """
        if not os.path.exists(cachedir):
            os.mkdir(cachedir)
        self.cachedir = cachedir

        self.shouldRun = True
        self.parent_pid = os.getpid()
        self.sha1_queue = multiprocessing.JoinableQueue()
        self.subproc = []
        # the processes log like this one (when they do not inherit its
        # logging configuration: not started by fork)
        log_level = logging.getLogger().getEffectiveLevel()
        if workers is None:
            workers = max(1, os.cpu_count() - 1)
        for num in range(workers):
            p = multiprocessing.Process(
                target=self.__subproc_thumbnail_create,
                args=(num, log_level),
                name=f"thumbnail-{num}",
                daemon=True,
            )
            p.start()
            self.subproc.append(p)

    def get_thumbname(self, sha1):
        thumbname = os.path.join(self.cachedir, sha1 + ".jpg")
        return thumbname

    def get_thumbnail(self, sha1):

        thumbname = self.get_thumbname(sha1)
        if not os.path.exists(thumbname):
            # not generated yet (or failed): a placeholder is shown
            log.debug("Missing thumbnail: %s", thumbname)
            return None

        # return the content of the whole jpeg
        with open(thumbname, 'rb') as f:
            return f.read()

    def thumbnail_info(self, sha1):
        """
        {'width', 'height', 'size', 'cmyk', 'mtime'} of the thumbnail of a
        book (pixels, bytes, seconds), None without thumbnail. width and height are None
        when the image can not be read; only its header is read
        (jpeg_info()). cmyk: an image in CMYK, whose colours are wrong in
        the browsers (made by an older version, see
        __pdf2jpeg_wand_only()).
        """
        thumbname = self.get_thumbname(sha1)
        try:
            st = os.stat(thumbname)
        except OSError:
            return None
        width, height, components = jpeg_info(thumbname) or (None, None, None)
        return {"width": width, "height": height, "size": st.st_size,
                "cmyk": components == 4, "mtime": st.st_mtime}

    def make_thumbnail(self, pdffilename, sha1, backend=None):
        """
        Make the thumbnail of a book now, in this process (not by the
        thumbnail processes), e.g. from the command line: True when done.
        The image is made in a temporary file of the cache directory, which
        then replaces the thumbnail: a thumbnail is never seen incomplete,
        and is kept when the new one can not be made.
        """
        return self._make_into(pdffilename, self.get_thumbname(sha1), backend)

    def _make_into(self, pdffilename, thumbname, backend=None):
        """
        Make the thumbnail thumbname in a temporary file (hidden, in the
        same directory), which replaces it once complete: True when done.
        The thumbnail processes do the same: the book page, which waits for
        a thumbnail to exist, never shows it unfinished (not resized yet).
        """
        dirname, name = os.path.split(thumbname)
        tmpname = os.path.join(dirname, f".{name}.{os.getpid()}.new.jpg")
        remove_quietly(tmpname)
        if self._thumbnail_job(pdffilename, tmpname, backend) and os.path.exists(tmpname):
            os.replace(tmpname, thumbname)
            return True
        remove_quietly(tmpname)
        return False

    def create_thumbnail(self, pdffilename, sha1, backend=None):
        """
        Queue the generation of the thumbnail of a book, unless it exists.
        backend: one of BACKENDS, None for each of them in turn.
        """
        if backend is not None and backend not in BACKENDS:
            raise ValueError(f"unknown thumbnail backend: {backend!r}")
        if not self.writable:
            return

        thumbname = self.get_thumbname(sha1)

        # Uncomment to avoid re-generation
        if os.path.exists(thumbname):
            return

        self._queue_thumbnail(pdffilename, thumbname, backend)

    def _queue_thumbnail(self, pdffilename, thumbname, backend=None):
        # Push thumbnail generation request to the process pool
        msg = (pdffilename, thumbname, backend)
        self.sha1_queue.put(msg)

    def __del__(self):
        self.shouldRun = False
        # TODO: in python3.14, replace by: [p.interrupt() for p in self.subproc]
        for p in self.subproc:
            try:
                os.kill(p.pid, signal.SIGINT)
            except:
                continue
        self.sha1_queue.close()
        self.sha1_queue.join_thread()

    def __enter__(self):
        """
        Following is python context manager within a class (with" block statement prelude)
        """
        return self.get_instance()

    def __exit__(self, exc_type, exc_value, traceback):
        """
        This is called automatically when exiting "with" block statement
        """
        self.get_instance().__del__()

    def __subproc_thumbnail_create(self, subprocId: int, log_level=logging.INFO):

        _reset_signal_handlers()
        setup_logging(log_level)
        log.info("Thumbnail process %d: waiting for orders", subprocId)
        while self.shouldRun:
            try:
                if os.getppid() != self.parent_pid:
                    log.info("Thumbnail process %d: parent process is gone, exit", subprocId)
                    break
                try:
                    (pdffilename, thumbname, backend) = self.sha1_queue.get(timeout=1)
                except queue.Empty:
                    continue

                self._make_into(pdffilename, thumbname, backend)
                continue

            except KeyboardInterrupt:
                log.info("Thumbnail process %d: exit working loop", subprocId)
                break

        return

    def _thumbnail_job(self, pdffilename, thumbname, backend=None):
        """
        A thumbnail request of the queue: True when the thumbnail is made.
        An error is logged, and no incomplete thumbnail is left (a
        placeholder is shown): it does not stop the process, which goes on
        with the next requests.
        """
        log.info("Thumbnail: %s -> %s (backend: %s)", pdffilename, thumbname, backend or "any")
        try:
            if self.__pdf2jpeg(pdffilename, thumbname, backend):
                return True
        except KeyboardInterrupt:
            raise
        except Exception:
            log.error("No thumbnail for %s", pdffilename, exc_info=True)
        remove_quietly(thumbname)
        return False

    def __pdf2jpeg(self, pdffilename, thumbname, backend=None):
        """
        Generate a Jpeg from a Pdf with a backend (one of BACKENDS), or with
        each of them in turn until one succeeds (None).
        When thumbnail is almost ready, resize it to a small memory footprint
        """
        jpeg_backends = {
            "pypdf-wand": self.__pdf2jpeg_resize_then_wand,
            "wand": self.__pdf2jpeg_wand_only,
            "ghostscript": self.__pdf2jpeg_ghostscript_jpeg,
        }
        names = [backend] if backend else BACKENDS

        jpegReady = False
        for name in names:
            jpegReady = jpeg_backends[name](pdffilename, thumbname)
            if jpegReady:
                break

        if jpegReady:
            self.__thumb_resize_small(thumbname)
        else:
            log.error("No thumbnail for %s (backend: %s)", pdffilename, backend or "any")
        return jpegReady


    def __pdf2jpeg_resize_then_wand(self, pdffilename, thumbname):
        """
        The first page copied alone (pypdf) to a temporary PDF file, then
        converted to JPEG (wand). The temporary file has a unique name,
        readable by this user only (tempfile), and is always removed.
        """
        try:
            with open(pdffilename, 'rb') as f:
                pdf = PdfReader(f)
                if pdf.is_encrypted:
                    pdf.decrypt('')
                # It has been observed working on a second call on some file.
                try:
                    contents = pdf.get_page(0)
                except Exception:
                    contents = pdf.pages[0]

                writer = PdfWriter()
                writer.add_page(contents)
                fd, inter = tempfile.mkstemp(prefix="ebookonline-thumb-", suffix=".pdf")
                try:
                    # (the source file is still open: the page is read from it)
                    with os.fdopen(fd, 'wb') as out:
                        writer.write(out)

                    # Generate image from first page (http://docs.wand-py.org/),
                    # in RGB (see __pdf2jpeg_wand_only()); the options are
                    # set before reading the file, to be used
                    with Image() as img:
                        img.options['pdf:use-cropbox'] = 'true'
                        img.read(filename=inter, colorspace="srgb")
                        img.alpha_channel = "remove"
                        img.save(filename=thumbname)
                finally:
                    remove_quietly(inter)
            return True

        except KeyboardInterrupt:
            raise
        except Exception:
            log.warning("Thumbnail with pypdf and wand failed for %s",
                        pdffilename, exc_info=True)
            return False


    def __pdf2jpeg_wand_only(self, pdffilename, thumbname):
        """
        The first page converted to JPEG by wand (ImageMagick). ImageMagick
        interprets the file names ('coder:' prefix, '[...]' frames, glob
        characters, '@' list), depending on its version: it reads a symbolic
        link to the PDF file, with a fixed name in a private temporary
        directory.

        The page is read in RGB (colorspace="srgb"). Otherwise, a PDF with
        CMYK colours (a printed cover) is rendered in CMYK by ImageMagick,
        and saved as a CMYK JPEG without colour profile: the browsers
        convert it to RGB naively, with wrong colours (a teal becomes a
        fluorescent green). Read in RGB, the page is converted by
        Ghostscript with its colour profiles, as by the Ghostscript backend.
        """
        try:
            log.info("Thumbnail of %s: trying with wand only", pdffilename)
            with tempfile.TemporaryDirectory(prefix="ebookonline-thumb-") as tmpdir:
                link = os.path.join(tmpdir, "book.pdf")
                os.symlink(os.path.abspath(pdffilename), link)
                with Image() as img:
                    img.options['pdf:use-cropbox'] = 'true'
                    img.read(filename=link + "[0]", colorspace="srgb")
                    img.save(filename=thumbname)
            return True
        except KeyboardInterrupt:
            raise
        except Exception:
            log.warning("Thumbnail with wand failed for %s", pdffilename,
                        exc_info=True)
            return False


    def __pdf2jpeg_ghostscript_jpeg(self, pdffilename, thumbname):
        """
        The first page of a PDF file as a JPEG image, with Ghostscript: True
        when the image is written. The command is run without shell, the file
        names as arguments: any name is safe ('"', '$(...)', a leading '-').
        No image is left when gs fails.
        """
        # absolute: a name can not be taken for an option; '%' would be a page
        # number in the output file name of gs
        pdfpath = os.path.abspath(pdffilename)
        output = os.path.abspath(thumbname).replace("%", "%%")
        resolution = 150
        while resolution >= 2:
            log.info("Thumbnail of %s: trying with Ghostscript (%d dpi)", pdffilename, resolution)
            cmd = ["gs", "-q", "-dSAFER", "-sDEVICE=jpeg", "-o", output, "-dFirstPage=1",
                   "-dLastPage=1", "-dJPEGQ=92", f"-r{resolution}", pdfpath]
            log.debug("%s", cmd)
            try:
                result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True,
                                        timeout=GS_TIMEOUT)
            except (OSError, subprocess.SubprocessError) as e:
                log.error("No thumbnail for %s: Ghostscript failed: %s", pdffilename, e)
                remove_quietly(thumbname)
                return False
            size = os.path.getsize(thumbname) if os.path.exists(thumbname) else 0
            if result.returncode != 0 or size == 0:
                log.error("No thumbnail for %s: Ghostscript failed (exit status %d): %s",
                          pdffilename, result.returncode,
                          result.stderr.decode(errors="replace").strip()[-500:])
                remove_quietly(thumbname)
                return False
            log.debug("Thumbnail size: %d bytes", size)
            if size < GS_MAX_IMAGE_BYTES:
                break
            resolution = resolution // 2
        return True

    def __thumb_resize_small(self, thumbname):

        # Try to resize the thumbnail to save network bandwith and overall disk space
        orig_filesize = float(os.stat(thumbname).st_size)

        with Image() as img:
            # 2nd pass jpeg->jpeg
            img.read(filename=thumbname)
            img.resize(width=300, height=math.floor(300*img.height/img.width))
            img.compression_quality = 85 # 92 by default
            img.save(filename=thumbname)

        resized_filesize = float(os.stat(thumbname).st_size)

        log.info("Thumbnail resized from %.2f KB to %.2f KB (ratio = %d %%)",
                 orig_filesize / 1024.0, resized_filesize / 1024.0,
                 resized_filesize * 100 / orig_filesize)


