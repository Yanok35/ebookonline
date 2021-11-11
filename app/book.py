#!/usr/bin/env python
# -*- coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4

import json
import sys

from app.cache import Cache
from app.cache import sha1_file

import os

def json_dumper(obj):
    try:
        return obj.to_json()
    except:
        return obj.__dict__

class Book:

    def __init__(self, sha1, book_dir, filename, category):

        # object variables
        fullpath = os.path.join(book_dir, filename)
        here = os.path.exists(fullpath)
        if not here:
            print("*** %s not here" % filename)
        self.sha1 = sha1
        self.mtime = os.path.getmtime(fullpath) if here else -1
        self.filename = filename
        self.category = category
        self.filesize = os.stat(fullpath).st_size if here else 0

        # following are user-defined books attributes
        # (mostly empty after scan_dir)
        self.tags = ""

    def __repr__(self):
        return (self.sha1 + '|' + self.filename)

    def get_name_and_size_as_str(self):
        return ("%s (%.2f MB)"
            % (os.path.basename(self.filename),
               (self.filesize / 1024.0 / 1024.0)))

    def get_json(self):
        return json.dumps(self, default=json_dumper, indent=2)

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
                sha1 = b["sha1"]
                filename = b["filename"]
                category = b["category"]
                new = Book(sha1, self.dirpath, filename, category)

                if "tags" in b.keys():
                    new.tags = b["tags"]

                # only append referenced PDF which still present on disk
                if os.path.exists(os.path.join(self.dirpath, filename)):
                    self.booklist.append(new)

    def save_db(self):
        with open(self.dbfile, "w") as f:
            s = json.dumps(self, default=json_dumper, indent=2)
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

        print("Open directory db...")
        self.dirpath = book_dir
        self.load_db()

        refreshed_booklist = []

        print("Scanning directory %s for PDF files..." % book_dir)
        for (dir, _, files) in os.walk(book_dir):

            # Book category is first level directory name
            category = dir.replace(book_dir, '')[1:]
            category = category.split('/')[0]
            if category == '':
                category = 'Generals'

            c = Cache.get_instance()
            for f in files:
                # Allow user to ignore some directories using a marker hidden file
                if (os.path.exists(dir + "/.ebook-ignore-dir")):
                    continue

                path = os.path.join(dir, f)
                if (path.lower().endswith("pdf")) and os.path.exists(path):
                    # a valid pdf filename has been found
                    print(" Scan '%s'... \r" % f, end='')

                    # Book object path are relative to BookDir path
                    abspath = path
                    path = os.path.relpath(path, book_dir)

                    # check if present in book database
                    b = self.find_book_by_filename(path)
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
                                  "already   \t%s" % (path, b.filename))
                            dup = True
                    if dup:
                        continue

                    # if file found in self.booklist, its a moved file
                    e = self.find_book_by_sha1(k)
                    if e:
                        # entry found in db and was moved in dir.
                        e.filename = path
                        e.mtime = os.path.getmtime(abspath)
                        e.category = category
                        e.filesize = os.stat(abspath).st_size

                        refreshed_booklist.append(e)
                        self.booklist.remove(e)
                        continue

                    # A new book which was not in db
                    b = Book(k, book_dir, path, category)
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

