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

import multiprocessing

from pypdf import PdfReader, PdfWriter

from wand.image import Image

from srcs.logs import setup_logging

log = logging.getLogger(__name__)

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

    def create_thumbnail(self, pdffilename, sha1):

        if not self.writable:
            return

        thumbname = self.get_thumbname(sha1)

        # Uncomment to avoid re-generation
        if os.path.exists(thumbname):
            return

        self._queue_thumbnail(pdffilename, thumbname)

    def _queue_thumbnail(self, pdffilename, thumbname):
        # Push thumbnail generation request to the process pool
        msg = (pdffilename, thumbname)
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

        setup_logging(log_level)
        log.info("Thumbnail process %d: waiting for orders", subprocId)
        while self.shouldRun:
            try:
                if os.getppid() != self.parent_pid:
                    log.info("Thumbnail process %d: parent process is gone, exit", subprocId)
                    break
                try:
                    (pdffilename, thumbname) = self.sha1_queue.get(timeout=1)
                except queue.Empty:
                    continue

                log.info("Thumbnail: %s -> %s", pdffilename, thumbname)
                self.__pdf2jpeg(pdffilename, thumbname)
                continue

            except KeyboardInterrupt:
                log.info("Thumbnail process %d: exit working loop", subprocId)
                break

        return

        # extract first page of PDF

    def __pdf2jpeg(self, pdffilename, thumbname):
        """
        Generate a Jpeg from a Pdf using different 'backends'
        When thumbnail is almost ready, resize it to a small memory footprint
        """
        jpeg_backends = [
            self.__pdf2jpeg_resize_then_wand,
            self.__pdf2jpeg_wand_only,
            self.__pdf2jpeg_ghostscript
        ]

        for callback in jpeg_backends:
            jpegReady = callback(pdffilename, thumbname)
            if jpegReady:
                break

        if jpegReady:
            self.__thumb_resize_small(thumbname)


    def __pdf2jpeg_resize_then_wand(self, pdffilename, thumbname):

        try:
            f = open(pdffilename, 'rb') 
            pdf = PdfReader(f)
            if pdf.is_encrypted:
                pdf.decrypt('')
            # It has been observed working on a second call on some file.
            try:
                contents = pdf.get_page(0)
            except:
                contents = pdf.pages[0]

            pdf = PdfWriter()
            pdf.add_page(contents)
            inter = f"/tmp/temp_output_{os.getpid()}.pdf"
            f = open(inter, 'wb') 
            pdf.write(f)
            f.close()

            # Generate image from first page

            # http://docs.wand-py.org/en/0.4.3/
            # sudo apt-get install python-wand

            with Image(filename=inter) as img:
                img.alpha_channel = "remove"
                img.options['pdf:use-cropbox'] = 'true'
                img.save(filename=thumbname)

            os.remove(inter)
            return True

        except KeyboardInterrupt:
            raise KeyboardInterrupt
        except:
            log.warning("Thumbnail with pypdf and wand failed for %s",
                        pdffilename, exc_info=True)
            return False


    def __pdf2jpeg_wand_only(self, pdffilename, thumbname):

        try:
            log.info("Thumbnail of %s: trying with wand only", pdffilename)
            with Image() as img:
                img.options['pdf:use-cropbox'] = 'true'
                img.read(filename=pdffilename+"[0]")
                img.save(filename=thumbname)
            return True
        except KeyboardInterrupt:
            raise KeyboardInterrupt
        except:
            log.warning("Thumbnail with wand failed for %s", pdffilename,
                        exc_info=True)
            return False


    def __pdf2jpeg_ghostscript(self, pdffilename, thumbname):

        try:
            resolution = int(150)
            while resolution >= 2:
                log.info("Thumbnail of %s: trying with Ghostscript (%d dpi)",
                         pdffilename, resolution)
                cmdLine = f'gs -sDEVICE=jpeg -o "{thumbname}" -dFirstPage=1 -dLastPage=1 -dJPEGQ=92 -r{resolution}x{resolution} "{pdffilename}"'
                log.debug("%s", cmdLine)
                retCode = os.system(cmdLine)
                log.debug("Ghostscript exit status: %d", retCode)
                if retCode != 0:
                    #raise "Ghostscript failed"
                    break
                filesize = os.stat(thumbname).st_size
                log.debug("Thumbnail size: %d bytes", filesize)
                if filesize < (2048 * 1024): # > 2MB
                    break

                resolution = resolution // 2
            return True
        except KeyboardInterrupt:
            raise KeyboardInterrupt
        except:
            log.error("No thumbnail for %s: Ghostscript failed", pdffilename,
                      exc_info=True)
            return False

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


