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

import json
import sys
import tempfile
import threading
from threading import Thread

from srcs.cache import Cache
from srcs.cache import sha1_file
from srcs.search import fuzzy_search

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

        self.filename = filename
        self.mtime = os.path.getmtime(fullpath) if here else -1
        self.filesize = os.stat(fullpath).st_size if here else 0

    @property
    def present(self):
        """
        False when the PDF file is missing from the book directory. Such
        books are kept in the database (bookmark, tags, ... are restored if
        the file comes back) but hidden from the views.
        """
        return self.mtime >= 0

    def mark_missing(self):
        self.filesize = 0
        self.mtime = -1

    def set_category(self, category):
        self.category = category

    def set_tags(self, tags):
        self.tags = tags

    def get_name_and_size_as_str(self):
        return ("%s (%.2f\u00A0MB)"
            % (os.path.basename(self.filename),
               (self.filesize / 1024.0 / 1024.0)))

    def to_json(self):
        d = {
            "sha1": self.sha1,
            "mtime": self.mtime,
            "filename": self.filename,
            "category": self.category,
            "filesize": self.filesize,
            "tags": self.tags,
            "bookmarked": self.bookmarked,
        }
        return d

class BookDir:
    """
    The list of books found in a directory, persisted in a JSON file.

    Thread-safety: the book list is never modified in place by a scan; a new
    list is built and swapped under self.lock, so readers iterating over
    self.booklist always see a consistent list. Scans are serialized by
    self._scan_lock (startup scan and rescans requested by the watcher).
    """

    def __init__(self, dbfile : str, cache : Cache):
        assert isinstance(cache, Cache)

        self.booklist = []
        self.cache = cache
        self.dbfile = dbfile
        self.dirpath = None

        self.lock = threading.RLock()
        self._scan_lock = threading.Lock()
        self._loaded = False

    def open(self, book_dir):
        """
        Set the book directory and load the database file, without scanning
        the directory (fast): the last known book list is available at once.
        """
        self.dirpath = book_dir
        self.load_db()

    def load_db(self):
        self._loaded = True

        if not os.path.exists(self.dbfile):
            return

        # When dbfile is empty, json parser trig an exception.
        if not os.stat(self.dbfile).st_size:
            print("Warning: dbfile is empty")
            return

        booklist = []
        with open(self.dbfile, "r") as f:
            inp = json.load(f)

            for b in inp['booklist']:
                # Books whose PDF is missing are kept (marked as missing by
                # set_filename), to restore their settings if they come back.
                new = Book(self.dirpath)
                new.set_sha1(b["sha1"])
                new.set_filename(b["filename"])
                new.set_category(b["category"])

                if "tags" in b.keys():
                    new.set_tags(b["tags"])

                if "bookmarked" in b.keys():
                    new.bookmarked = b["bookmarked"]

                booklist.append(new)

        with self.lock:
            self.booklist = booklist

    def to_json(self):
        d = {
            'dirpath': self.dirpath,
            'booklist': [ b.to_json() for b in self.booklist ],
        }
        return d

    def save_db(self):
        """
        Write the database in a temporary file, then replace the previous
        one, so that an interruption can not leave a truncated JSON file.
        """
        with self.lock:
            s = json.dumps(self.to_json(), default=lambda o: o.__dict__, indent=2)

            dbdir = os.path.dirname(os.path.abspath(self.dbfile))
            fd, tmpname = tempfile.mkstemp(prefix=".book_db_", suffix=".tmp", dir=dbdir)
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(s)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmpname, self.dbfile)
            finally:
                if os.path.exists(tmpname):
                    os.unlink(tmpname)

    def find_book_by_sha1(self, sha1):
        """ Search all books, including missing ones (admin page) """
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
        """ Books whose PDF is present in the book directory """
        return [b for b in self.booklist if b.present]

    def get_all_books(self):
        """ All books of book.db, including the missing ones (admin page) """
        return list(self.booklist)

    def get_subset_if_bookmarked(self, srclist = None):
        sublist = []
        if not srclist:
            srclist = self.get_booklist()

        for b in srclist:
            if b.bookmarked:
                sublist.append(b)
        return sublist

    def get_subset_by_category(self, category, srclist = None):
        sublist = []
        if not srclist:
            srclist = self.get_booklist()

        for b in srclist:
            if b.category == category:
                sublist.append(b)
        return sublist

    def get_subset_by_regexp(self, pattern, srclist = None):
        sublist = []
        if not srclist:
            srclist = self.get_booklist()

        for b in srclist:
            name = b.filename.lower()
            if name.endswith(".pdf"):
                name = name[:-4]
            name = name.replace(".", " ")
            name = name.replace("-", " ")
            name = name.replace("_", " ")
            name = name.replace("'", "")
            if pattern.lower() in name:
                sublist.append(b)
        return sublist

    def search(self, pattern, books=None):
        """
        Typo tolerant search in 'books' (default: all present books), most
        relevant first. See srcs/search.py.
        """
        if books is None:
            books = self.get_booklist()
        return fuzzy_search(books, pattern)

    def sort_by_date(self):
        return sorted(
            self.get_booklist(),
            key=lambda b: (-b.mtime, b.filename)
        )

    def get_list_of_category(self):
        categories = []
        for b in self.get_booklist():
            if not b.category in categories:
                categories.append(b.category)
        return categories

    def get_list_of_tags(self):
        tags = []
        for b in self.get_booklist():
            for t in b.tags.split(' '):
                if not t in tags:
                    tags.append(t)
        return tags

    def scan_dir(self, book_dir):
        """
            Refresh the database content by searching for PDF files in
            'book_dir' filesystem tree, in a background thread.

            The filename is researched, and if found, the mtime is checked.
            If both match between dbfile and book_dir entry, then the dbfile
            cached informations are considered consistents and reused.
        """
        self.dirpath = book_dir
        if not self._loaded:
            self.load_db()
        thr = Thread(target=self.rescan, name="bookdir-scan", daemon=True)
        thr.start()
        return thr

    def rescan(self):
        """
        Synchronize the book list with the content of the book directory:
        new PDF are added (and their thumbnail requested), moved PDF are
        detected by their sha1, missing PDF are kept but marked as missing.
        Only new or modified files are hashed.
        """
        with self._scan_lock:
            changed = self.__rescan()
        return changed

    def __rescan(self):
        book_dir = self.dirpath

        # Work on a copy: requests keep using the current list until the new
        # one is complete. Book objects are shared, so a bookmark toggled
        # during the scan is not lost.
        with self.lock:
            remaining = list(self.booklist)
        refreshed_booklist = []
        changed = False

        def take(book):
            remaining.remove(book)
            refreshed_booklist.append(book)

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

            # For all files found in current directory
            for f in files:
                abspath = os.path.join(dir, f)
                if not abspath.lower().endswith("pdf"):
                    continue
                try:
                    mtime = os.path.getmtime(abspath)
                    filesize = os.stat(abspath).st_size
                except OSError:
                    # removed in the meantime (or dangling symlink)
                    continue

                # Book object path are relative to BookDir path
                relpath = os.path.relpath(abspath, book_dir)

                # check if present in book database, unchanged
                b = next((b for b in remaining if b.filename == relpath), None)
                if b and b.mtime == mtime:
                    # Let's create thumbnail, in case it is missing for
                    # any reason
                    self.cache.create_thumbnail(abspath, b.sha1)
                    take(b)
                    continue

                print("Compute sha1 for %s..." % f, end="")
                sys.stdout.flush()
                try:
                    k = sha1_file(abspath)
                except OSError as e:
                    print("failed: %s" % e)
                    continue
                print("done")
                changed = True

                # if file found in refreshed_booklist, its a duplicate
                dup = next((b for b in refreshed_booklist
                            if b.sha1 == k and b.filesize), None)
                if dup:
                    print("*** Warning: duplicate PDF files:\n"
                          "not adding\t%s\n"
                          "already   \t%s" % (relpath, dup.filename))
                    continue

                # if file found in remaining books, it is a moved (or
                # modified, or reappeared) file: keep its user settings
                e = next((b for b in remaining if b.sha1 == k), None)
                if e:
                    print("Book moved: '%s' -> '%s'" % (e.filename, relpath))
                    e.filename = relpath
                    e.mtime = mtime
                    e.category = category
                    e.filesize = filesize
                    self.cache.create_thumbnail(abspath, k)
                    take(e)
                    continue

                # Same path but new content (file replaced in place): same
                # book entry, user settings kept, new sha1 and thumbnail
                if b:
                    print("Book modified: '%s'" % relpath)
                    b.sha1 = k
                    b.mtime = mtime
                    b.filesize = filesize
                    self.cache.create_thumbnail(abspath, k)
                    take(b)
                    continue

                # A new book which was not in db
                print("New book: '%s'" % relpath)
                b = Book(book_dir)
                b.set_sha1(k)
                b.set_filename(relpath)
                b.set_category(category)
                self.cache.create_thumbnail(abspath, k)

                refreshed_booklist.append(b)

        # remaining contains all db entries not found in dir, thus removed.
        # let's keep those entry to keep user settings in case they reappears
        for b in remaining:
            if b.present:
                print("Book missing: '%s'" % b.filename)
                changed = True
            b.mark_missing()
            refreshed_booklist.append(b)

        with self.lock:
            self.booklist = refreshed_booklist
            print("Directory db fully parsed. Save JSON db file...")
            self.save_db()

        return changed
