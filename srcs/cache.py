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

import hashlib
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

from srcs.logs import setup_logging

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


def _remove(filename):
    try:
        os.remove(filename)
    except FileNotFoundError:
        pass


def sha1_file(filename):
    with open(filename, 'rb') as fd_in:
        digest = hashlib.file_digest(fd_in, "sha1")
        return digest.hexdigest()

class Cache:

    instance = None
    file_list = []
    # False when the cache directory can not be written (see srcs.access):
    # no thumbnail is generated.
    writable = True

    @classmethod
    def get_instance(cls, *args):
        if cls.instance == None:
            log.debug("Cache instance: %s", args)
            cls.instance = cls(*args)
        return cls.instance

    def __init__(self, cachedir):
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
        for num in range(max(1, os.cpu_count()-1)):
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

                self._thumbnail_job(pdffilename, thumbname, backend)
                continue

            except KeyboardInterrupt:
                log.info("Thumbnail process %d: exit working loop", subprocId)
                break

        return

    def _thumbnail_job(self, pdffilename, thumbname, backend=None):
        """
        A thumbnail request of the queue. An error is logged, and no
        incomplete thumbnail is left (a placeholder is shown): it does not
        stop the process, which goes on with the next requests.
        """
        log.info("Thumbnail: %s -> %s (backend: %s)", pdffilename, thumbname, backend or "any")
        try:
            self.__pdf2jpeg(pdffilename, thumbname, backend)
        except KeyboardInterrupt:
            raise
        except Exception:
            log.error("No thumbnail for %s", pdffilename, exc_info=True)
            _remove(thumbname)

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

                    # Generate image from first page (http://docs.wand-py.org/)
                    with Image(filename=inter) as img:
                        img.alpha_channel = "remove"
                        img.options['pdf:use-cropbox'] = 'true'
                        img.save(filename=thumbname)
                finally:
                    _remove(inter)
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
        """
        try:
            log.info("Thumbnail of %s: trying with wand only", pdffilename)
            with tempfile.TemporaryDirectory(prefix="ebookonline-thumb-") as tmpdir:
                link = os.path.join(tmpdir, "book.pdf")
                os.symlink(os.path.abspath(pdffilename), link)
                with Image() as img:
                    img.options['pdf:use-cropbox'] = 'true'
                    img.read(filename=link + "[0]")
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
                _remove(thumbname)
                return False
            size = os.path.getsize(thumbname) if os.path.exists(thumbname) else 0
            if result.returncode != 0 or size == 0:
                log.error("No thumbnail for %s: Ghostscript failed (exit status %d): %s",
                          pdffilename, result.returncode,
                          result.stderr.decode(errors="replace").strip()[-500:])
                _remove(thumbname)
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


