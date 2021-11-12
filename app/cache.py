#!/usr/bin/env python
# -*- coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4

import hashlib
import os
import shutil
import sys
import math

#from pdfrw import PdfReader, PdfWriter

#CACHE_DIR = os.path.abspath("cache")
#BOOK_DIR = os.path.abspath("books")

import multiprocessing
from multiprocessing import Process

def sha1_file(filename):
    if not os.path.exists(filename):
        raise getopt.error("file %s not found" % str(filename))

    fd_in = open(filename, 'rb')
    allin = fd_in.read() #.decode('latin1')#.decode('iso8859-15')

    m = hashlib.sha1()
    m.update(allin)
    return m.hexdigest()

class Cache:

    instance = None
    file_list = []

    @classmethod
    def get_instance(cls, *args):
        if cls.instance == None:
            #print(**args)
            #print(*args)
            print(args)
            cls.instance = cls(*args)
        return cls.instance

    def __init__(self, cachedir):
        if not os.path.exists(cachedir):
            os.mkdir(cachedir)
        self.cachedir = cachedir
        #self.generate_all_thumbs()

        self.sha1_queue = multiprocessing.Queue()
        self.subproc = []
        for num in range(max(1, os.cpu_count()-1)):
            p = multiprocessing.Process(target=self.__subproc_thumbnail_create, args=(num,))
            p.start()
            self.subproc.append(p)

    def get_thumbname(self, sha1):
        thumbname = os.path.join(self.cachedir, sha1 + ".jpg")
        return thumbname

    def get_thumbnail(self, sha1):

        thumbname = self.get_thumbname(sha1)
        if not os.path.exists(thumbname):
            print("*** Error: missing thumbnail : %s" % thumbname)
            return None

        # return the content of the whole jpeg
        with open(thumbname, 'rb') as f:
            return f.read()

    def create_thumbnail(self, pdffilename, sha1):

        thumbname = self.get_thumbname(sha1)

        # Uncomment to avoid re-generation
        if os.path.exists(thumbname):
            return

        # Push thumbnail generation request to the process pool
        msg = (pdffilename, thumbname)
        self.sha1_queue.put(msg)

    def __del__(self):
        self.sha1_queue.close()
        self.sha1_queue.join_thread()

    def __subproc_thumbnail_create(self, subprocId: int):

        while True:
            print(f"{subprocId}: waiting for orders")

            try:
                (pdffilename, thumbname) = self.sha1_queue.get()

                print(f"{subprocId}, {os.getpid()}: thumb gen: {pdffilename} -> {thumbname}")
                self.__pdf2jpeg(pdffilename, thumbname)
                continue

            except KeyboardInterrupt:
                print(f"{subprocId}: exit working loop")
                break

        return

        # extract first page of PDF

    def __pdf2jpeg(self, pdffilename, thumbname):
        try:
            #from pyPdf import PdfFileReader, PdfFileWriter
            from PyPDF2 import PdfFileReader, PdfFileWriter
            f = open(pdffilename, 'rb') 
            pdf = PdfFileReader(f)
            if pdf.isEncrypted:
                pdf.decrypt('')
            # It has been observed working on a second call on some file.
            try:
                contents = pdf.getPage(0)
            except:
                contents = pdf.pages[0]

            pdf = PdfFileWriter()
            pdf.addPage(contents)
            inter = f"/tmp/temp_output_{os.getpid()}.pdf"
            f = open(inter, 'wb') 
            pdf.write(f)
            f.close()

            # Generate image from first page

            # http://docs.wand-py.org/en/0.4.3/
            # sudo apt-get install python-wand

            from wand.image import Image
            with Image() as img:
                img.options['pdf:use-cropbox'] = 'true'
                img.read(filename=inter)
                img.save(filename=thumbname)

            os.remove(inter)

        except:
            print(u"\u001b[36m")
            print(">>>")
            print('Error: thumbnail generation failed')
            print('pdffilename = %s' % pdffilename)
            print("Unexpected error:")
            print(sys.exc_info())
            import traceback
            print (traceback.print_exc())
            print ('<<<')
            print (u"\u001b[0m")

            try:
                print("--- trying with wand library ---")
                from wand.image import Image
                with Image() as img:
                    img.options['pdf:use-cropbox'] = 'true'
                    img.read(filename=pdffilename+"[0]")
                    img.save(filename=thumbname)
            except:
                print (u"\u001b[36m")
                print (traceback.print_exc())
                print (u"\u001b[0m")
                try:
                    resolution = int(150)
                    while resolution >= 2:
                        print(f"--- trying with Ghostscript -sDEVICE=jpeg ({resolution} dpi) ---")
                        cmdLine = f'gs -sDEVICE=jpeg -o "{thumbname}" -dFirstPage=1 -dLastPage=1 -dJPEGQ=92 -r{resolution}x{resolution} "{pdffilename}"'
                        print(cmdLine)
                        retCode = os.system(cmdLine)
                        print(f"retcode = {retCode}")
                        if retCode != 0:
                            #raise "Ghostscript failed"
                            break
                        filesize = os.stat(thumbname).st_size
                        print(f"filesize = {filesize} Bytes")
                        if filesize < (2048 * 1024): # > 2MB
                            break

                        resolution = resolution // 2

                except:
                    print (u"\u001b[36m")
                    print (traceback.print_exc())
                    print (u"\u001b[0m")
                    print("--- Failed ---")
                    print (u"\u001b[33mNo thumbnail for '%s'\u001b[0m" % pdffilename)
                    return

        # Try to resize the thumbnail to save network bandwith and overall disk space
        orig_filesize = float(os.stat(thumbname).st_size)

        with Image() as img:
            # 2nd pass jpeg->jpeg
            img.read(filename=thumbname)
            img.resize(width=300, height=math.floor(300*img.height/img.width))
            img.compression_quality = 85 # 92 by default
            img.save(filename=thumbname)

        resized_filesize = float(os.stat(thumbname).st_size)

        print("filesize orig: %.2f KB resize: %.2f KB (ratio = %d %%)"
              % (orig_filesize / 1024.0,
                 resized_filesize / 1024.0,
                 resized_filesize * 100 / orig_filesize) )


    #def generate_all_thumbs(self):
    #    assert(self.cachedir)

    #    for (dir, _, files) in os.walk(self.cachedir):
    #        for f in files:
    #            path = os.path.join(dir, f)
    #            print("=== cache:\t%s" % path)



### #file_list = {}
### 
### #cache
### # keys: sha1 (string),
### cache = {
###     '': (
###         # path:
###         '',
###         # jsonfile?
###     )
### }
### 
### def cache_init():
###     #global file_list
### 
###     #if not os.path.exists(CACHE_DIR):
###     #    os.mkdir(CACHE_DIR)
###     return Cache(CACHE_DIR)
### 
###     #print("Scanning directory %s for PDF files..." % BOOK_DIR)
###     #for (dir, _, files) in os.walk(BOOK_DIR):
###     #    for f in files:
###     #        path = os.path.join(dir, f)
###     #        if (path.lower().endswith("pdf")) and os.path.exists(path):
###     #            print("\t" + path)
###     #            #file_list[path] = sha1_file(path)
###     #            k = sha1_file(path)
###     #            if k in cache.keys():
###     #                e = cache[k]
###     #                (e_path,) = e
###     #                print(" *** Warning: duplicate PDF files: %s\n"
###     #                      " (%s already in cache)" % (path, e_path))
###     #                continue
### 
###     #            cache[k] = (path,)
### 
###     #print("\n")
###     #for k in cache.keys():
###     #    if not k: continue
### 
###     #    print(".\t"+k)
###     #    print("\t",cache[k])
###     #return
###     for filename in file_list.keys():
###         cache_sha1 = file_list[filename]
###         print "%s => %s" % (cache_sha1, filename)
### 
###         thumbname = os.path.join(CACHE_DIR, cache_sha1 + ".jpg")
###         if os.path.exists(thumbname):
###             print("%s found in cache" % filename)
###         else:
###             print("%s not in cache, create new %s" % (filename, thumbname))
###             pdf2thumbnail(filename, thumbname)
### 
###     print("number of book = %d" % len(file_list))
### 
### def cache_nb_entries():
###     global file_list
###     return len(file_list)
### 
