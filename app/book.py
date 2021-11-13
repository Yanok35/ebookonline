#!/usr/bin/env python
# -*- coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4

import json
import sys
from threading import Thread

from app.cache import Cache
from app.cache import sha1_file

import os

class Book:

    def __init__(self, book_dir):

        # object variables
        self.book_dir = book_dir
        self.sha1 = None
        self.filename = None
        self.mtime = -1
        self.filesize = 0

        # Following are user-defined books attributes
        # - prefilled at book insertion (parent dirname)
        self.category = None

        # - empty after scan_dir
        self.year = 0
        self.editor = ""
        self.isbn = ""
        self.tags = ""

        # - those one should be user related/preferences
        self.score = 0 # between 0..5
        self.bookmarked = False
        self.nb_time_opened = 0

    def set_sha1(self, sha1):
        self.sha1 = sha1

    def set_filename(self, filename):
        fullpath = os.path.join(self.book_dir, filename)
        here = os.path.exists(fullpath)
        if not here:
            print("*** %s not here" % filename)

        self.filename = filename
        self.mtime = os.path.getmtime(fullpath) if here else -1
        self.filesize = os.stat(fullpath).st_size if here else 0

    def set_category(self, category):
        self.category = category

    def set_tags(self, tags):
        self.tags = tags

    def get_name_and_size_as_str(self):
        return ("%s (%.2f\u00A0MB)"
            % (os.path.basename(self.filename),
               (self.filesize / 1024.0 / 1024.0)))

    def to_json(self):
        j = {
            "sha1": self.sha1,
            "mtime": self.mtime,
            "filename": self.filename,
            "category": self.category,
            "filesize": self.filesize,
            "tags": self.tags
        }
        return json.dumps(j, default=lambda o: o.__dict__, indent=2)

class BookDir:

    def __init__(self, dbfile):
        self.booklist = []
        self.dbfile = dbfile
        self.dirpath = None

    def load_db(self):
        if not os.path.exists(self.dbfile):
            return

        self.booklist = []

        # When dbfile is empty, json parser trig an exception.
        if not os.stat(self.dbfile).st_size:
            print("Warning: dbfile is empty")
            return

        with open(self.dbfile, "r") as f:
            inp = json.load(f)

            for b in inp['booklist']:
                # only append referenced PDF which still present on disk
                if not os.path.exists(os.path.join(self.dirpath, b["filename"])):
                    continue

                new = Book(self.dirpath)
                new.set_sha1(b["sha1"])
                new.set_filename(b["filename"])
                new.set_category(b["category"])

                if "tags" in b.keys():
                    new.set_tags(b["tags"])

                self.booklist.append(new)

    def save_db(self):
        with open(self.dbfile, "w") as f:
            s = json.dumps(self, default=lambda o: o.__dict__, indent=2)
            f.write(s)

    def find_book_by_sha1(self, sha1):
        for b in self.booklist:
            if b.sha1 == sha1:
                return b
        return None

    def find_book_by_filename(self, filename):
        for b in self.booklist:
            if b.filename == filename:
                return b
        return None

    def get_booklist(self):
        return self.booklist

    def get_subset_by_category(self, category):
        sublist = []
        for b in self.booklist:
            if b.category == category:
                sublist.append(b)
        return sublist

    def get_subset_by_regexp(self, pattern):
        sublist = []
        for b in self.booklist:
            name = b.filename.lower()
            if name.endswith(".pdf"):
                name = name[:-4]
            name = name.replace(".", " ")
            name = name.replace("-", " ")
            name = name.replace("_", " ")
            if pattern.lower() in name:
                sublist.append(b)
        return sublist

    def get_list_of_category(self):
        categories = []
        for b in self.booklist:
            if not b.category in categories:
                categories.append(b.category)
        return categories

    def get_list_of_tags(self):
        tags = []
        for b in self.booklist:
            for t in b.tags.split(' '):
                if not t in tags:
                    tags.append(t)
        return tags

    def scan_dir(self, book_dir):
        """
            Open 'dbfile' (JSon format) and refresh its content by searching
            for PDF files in 'book_dir' filesystem tree.

            The filename is researched, and if found, the mtime is checked.
            If both match between dbfile and book_dir entry, then the dbfile
            cached informations are considered consistents and reused.
        """
        self.dirpath = book_dir
        thr = Thread(target=self.__scan_dir_thr, args=(book_dir,))
        thr.start()

    def __scan_dir_thr(self, book_dir):

        print("Open directory db...")
        self.load_db()

        refreshed_booklist = []

        print("Scanning directory %s for PDF files..." % book_dir)
        for (dir, _, files) in os.walk(book_dir):

            # Allow user to ignore some directories using a marker hidden file
            if (os.path.exists(dir + "/.ebook-ignore-dir")):
                continue

            # Book category is first level directory name
            category = dir.replace(book_dir, '')[1:]
            category = category.split('/')[0]
            if category == '':
                category = 'Generals'

            c = Cache.get_instance()
            # For all files found in current directory
            for f in files:
                abspath = os.path.join(dir, f)
                if (abspath.lower().endswith("pdf")) and os.path.exists(abspath):
                    # a valid pdf filename has been found
                    print(" Scan '%s'... \r" % f, end='')

                    # Book object path are relative to BookDir path
                    relpath = os.path.relpath(abspath, book_dir)

                    # check if present in book database
                    b = self.find_book_by_filename(relpath)
                    if b and b.mtime == os.path.getmtime(abspath):
                        # Let's create thumbnail, in case it is missing for
                        # any reason
                        c.create_thumbnail(abspath, b.sha1)

                        refreshed_booklist.append(b)
                        self.booklist.remove(b)
                        continue

                    print ("Compute sha1 for %s..." % f, end="")
                    sys.stdout.flush()
                    k = sha1_file(abspath)
                    print ("done")

                    # if file found in refreshed_booklist, its a duplicate
                    dup = False
                    for b in refreshed_booklist:
                        if b.sha1 == k and b.filesize:
                            print("*** Warning: duplicate PDF files:\n"
                                  "not adding\t%s\n"
                                  "already   \t%s" % (relpath, b.filename))
                            dup = True
                    if dup:
                        continue

                    # if file found in self.booklist, its a moved file
                    e = self.find_book_by_sha1(k)
                    if e:
                        # entry found in db and was moved in dir.
                        e.filename = relpath
                        e.mtime = os.path.getmtime(abspath)
                        e.category = category
                        e.filesize = os.stat(abspath).st_size

                        refreshed_booklist.append(e)
                        self.booklist.remove(e)
                        continue

                    # A new book which was not in db
                    b = Book(book_dir)
                    b.set_sha1(k)
                    b.set_filename(relpath)
                    b.set_category(category)
                    c.create_thumbnail(abspath, k)

                    refreshed_booklist.append(b)

        # booklist still contains all db file not found in dir, thus removed.
        # let's keep those entry to keep user settings in case they reappears
        books_notfound = self.booklist
        self.booklist = refreshed_booklist
        for b in books_notfound:
            b.filesize = 0
            b.mtime = -1
            self.booklist.append(b)

        print("\nDirectory db fully parsed. Save JSON db file...")
        self.save_db()

