#!/usr/bin/env python
# -*- coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4

from __future__ import unicode_literals

import sys

from cache import Cache
from cache import sha1_file
from flask import *

import os

class Book:

    def __init__(self, sha1, filename, category):

        # object variables
        self.sha1 = sha1
        self.mtime = os.path.getmtime(filename)
        self.filename = filename
        self.category = category
        self.filesize = os.stat(filename).st_size
        
    
    def __str__(self):
        return (self.sha1 + '|' + self.filename)

    def get_name_and_size_as_str(self):
        return ("%s (%.2f MB)"
            % (os.path.basename(self.filename),
               (self.filesize / 1024.0 / 1024.0)))

    # class variables
    book_list = []

    @classmethod
    def _load_bookdb_from_file(cls, dbfile):
        if os.path.exists(dbfile):
            cls.book_list = []

            with open(dbfile, "r") as f:
                book_list = json.load(f)

                for b in book_list['books']:
                    sha1 = b["sha1"]
                    filename = b["filename"]
                    category = b["category"]
                    new = Book(sha1, filename, category)

                    new.mtime = b["mtime"]
                    new.filesize = b["filesize"]

                    cls.book_list.append(new)

    @classmethod
    def save_bookdb_to_file(cls, dbfile):
        with open(dbfile, "w") as f:
            buf = []

            for b in cls.book_list:
                buf.append(json.dumps(b.__dict__, indent=2))

            all  = '{\n'
            all += ' "nb_books": "' + str(len(cls.book_list)) + '",\n'
            all += ' "books": [\n'
            all += ',\n'.join(buf) + "\n]\n}\n"

            f.write(all)
            f.close()

    @classmethod
    def find_book_by_sha1(cls, sha1):
        for b in cls.book_list:
            if b.sha1 == sha1:
                return b
        return None

    @classmethod
    def find_book_by_filename(cls, filename):
        for b in cls.book_list:
            if b.filename == filename:
                return b
        return None

    @classmethod
    def scan_dir(cls, dbfile, book_dir):
        """
            Open 'dbfile' (JSon format) and refresh its content by searching
            for PDF files in 'book_dir' filesystem tree.

            The filename is researched, and if found, the mtime is checked.
            If both match between dbfile and book_dir entry, then the dbfile
            cached informations are considered consistents and reused.
        """
        print("Open directory db...")
        cls._load_bookdb_from_file(dbfile)
        print("Scanning directory %s for PDF files..." % book_dir)
        for (dir, _, files) in os.walk(book_dir):

            #print('>>>', dir, files)

            # Book category is first level directory name
            category = dir.replace(book_dir, '')
            category = category.split('/')[0]
            if category == '':
                category = 'Generals'
            #print(category)

            c = Cache.get_instance()
            for f in files:
                path = os.path.join(dir, f)
                if (path.lower().endswith("pdf")) and os.path.exists(path):
                    # a valid pdf filename has been found, check if present in
                    # book database previously loaded
                    b = cls.find_book_by_filename(path)
                    if b and b.mtime == os.path.getmtime(path):
                        # Let's create thumbnail, in case it is missing for
                        # any reason
                        c.create_thumbnail(path, b.sha1)
                        continue

                    # TODO: keep a reference to current filename in
                    # dir_book_list[]

                    print "Compute sha1 for %s..." % f,
                    sys.stdout.flush()
                    k = sha1_file(path)
                    print "done"

                    e = cls.find_book_by_sha1(k)
                    if e:
                        print("*** Warning: duplicate PDF files:\n"
                              "adding \t%s\n"
                              "already\t%s" % (path, e.filename))
                        continue

                    b = Book(k, path, category)
                    c.create_thumbnail(path, k)
                    cls.book_list.append(b)

            cls.save_bookdb_to_file(dbfile)

        # Directory traversal is finished:
        # TODO: check if some book_list entries are
        # referering to obsolete pdf file not present in dir_book_list[] anymore

