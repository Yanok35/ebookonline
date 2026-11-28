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

"""
The book directory and its books: the index (book.db, see bookdb.py), the
queries, the scan. The operations on its files are in operations.py, the
transformations of a book file in transform.py.
"""

import logging
import os
import shutil
import threading
from threading import Thread

from srcs.common.files import sha1_file
from srcs.library import bookdb
from srcs.library.book import Book, PdfFile
from srcs.library.fileops import IGNORE_MARKER, BookFileError
from srcs.library.search import fuzzy_search
from srcs.pdf.thumbnails import Cache

log = logging.getLogger(__name__)


class BookDir:
    """
    The list of books found in a directory, persisted in a JSON file.

    Thread-safety: the book list is never modified in place by a scan; a new
    list is built and swapped under self.lock, so readers iterating over
    self.booklist always see a consistent list. Scans are serialized by
    self._scan_lock (startup scan and rescans requested by the watcher).
    """

    def __init__(self, dbfile : str, cache : Cache, read_only=False):
        assert isinstance(cache, Cache)

        self.booklist = []
        # Other files having the content of a book ([PdfFile])
        self.duplicates = []
        self.cache = cache
        # srcs.metadata.service.MetadataService, or None: asked to analyse
        # the books found by the scans
        self.metadata = None
        self.dbfile = dbfile
        self.dirpath = None

        self.lock = threading.RLock()
        self._scan_lock = threading.Lock()
        self._loaded = False

        # Nothing is written, neither book.db nor the files of the book
        # directory: changes are kept in memory only. Given when the server
        # can not write (see srcs.common.access), or set by load_db() for a book.db
        # written by a newer version of ebookonline, but readable by this one.
        self.read_only = read_only
        # Schema version of the book.db file, when newer than bookdb.DB_VERSION
        self.db_version = None

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
            log.warning("%s is empty", self.dbfile)
            return

        booklist, duplicates, version = bookdb.read(self.dbfile, self.dirpath)
        if version > bookdb.DB_VERSION:
            log.warning("%s: schema version %d is newer than the supported "
                        "version %d: read-only, changes are kept in memory only",
                        self.dbfile, version, bookdb.DB_VERSION)
            self.read_only = True
            self.db_version = version

        with self.lock:
            self.booklist = booklist
            self.duplicates = duplicates

        if version < bookdb.DB_VERSION and self.read_only:
            log.warning("%s: schema version %d is migrated to %d in memory "
                        "only (read-only)", self.dbfile, version, bookdb.DB_VERSION)
        elif version < bookdb.DB_VERSION:
            # Keep the file of the previous version, the first time only
            backup = f"{self.dbfile}.v{version}.bak"
            if not os.path.exists(backup):
                shutil.copy2(self.dbfile, backup)
            log.info("Migrate %s from schema version %d to %d (backup: %s)",
                     self.dbfile, version, bookdb.DB_VERSION, backup)
            self.save_db()

    def to_json(self):
        return bookdb.to_json(self.dirpath, self.booklist, self.duplicates)

    def save_db(self):
        """
        Write the database in a temporary file, then replace the previous
        one, so that an interruption can not leave a truncated JSON file.
        Nothing is written when read-only.
        """
        if self.read_only:
            return
        with self.lock:
            bookdb.write(self.dbfile, self.to_json())

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

    def get_duplicates(self):
        """
        {sha1: [PdfFile]}: for each book having duplicates, the other files
        with the same content, sorted by path.
        """
        duplicates = {}
        for d in sorted(self.duplicates, key=lambda d: d.filename):
            duplicates.setdefault(d.sha1, []).append(d)
        return duplicates

    def get_subset_by_category(self, category, srclist = None):
        sublist = []
        if not srclist:
            srclist = self.get_booklist()

        for b in srclist:
            if b.category == category:
                sublist.append(b)
        return sublist

    def search(self, pattern, books=None):
        """
        Typo tolerant search in 'books' (default: all present books), most
        relevant first. See srcs/library/search.py.
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

    def _check_writable(self):
        if self.read_only:
            raise BookFileError("read-only mode: the book directory is not modified")

    def _present_book(self, sha1):
        self._check_writable()
        book = self.find_book_by_sha1(sha1)
        if book is None:
            raise BookFileError(f"unknown book: {sha1}")
        if not book.present or not os.path.isfile(os.path.join(self.dirpath, book.filename)):
            raise BookFileError(f"the file of the book is missing: {book.filename}")
        return book

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

    def pdf_files(self):
        """
        [PdfFile] of the PDF files of the book directory, books and
        duplicates, without changing anything (e.g. for the command line).
        The sha1 of a file known at this path with this modification time
        is not computed again; the other files are hashed.
        """
        with self.lock:
            books = list(self.booklist)
            duplicates = list(self.duplicates)
        return self._list_pdf_files(self.dirpath, books, duplicates)[0]

    def rescan(self):
        """
        Synchronize the book list with the content of the book directory:
        new PDF are added (and their thumbnail requested), moved PDF are
        detected by their sha1, missing PDF are kept but marked as missing.
        Only new or modified files are hashed.
        """
        with self._scan_lock:
            changed = self._rescan()
        return changed

    def _rescan(self):
        book_dir = self.dirpath

        # Work on a copy: requests keep using the current list until the new
        # one is complete. Book objects are shared, so a bookmark toggled
        # during the scan is not lost.
        with self.lock:
            books = list(self.booklist)
            known_duplicates = list(self.duplicates)
        # the books not found yet, by sha1 (unique), in the order of the list
        remaining = {b.sha1: b for b in books}
        by_filename = {}
        for b in books:
            by_filename.setdefault(b.filename, []).append(b)
        refreshed_booklist = []
        refreshed_duplicates = []
        changed = False

        def take(book):
            del remaining[book.sha1]
            refreshed_booklist.append(book)

        def remaining_at(filename):
            return next((b for b in by_filename.get(filename, ())
                         if remaining.get(b.sha1) is b), None)

        # 1. List the PDF files of the directory, with their sha1. Only new
        #    or modified files are hashed.
        files, hashed = self._list_pdf_files(book_dir, books, known_duplicates)
        changed |= hashed

        # 2. Group the files by content (sha1). The first file of a group is
        #    the book, the other ones are duplicates. Files are sorted, so
        #    that the result does not depend on the directory walk order.
        groups = {}
        for f in sorted(files, key=lambda f: f.filename):
            groups.setdefault(f.sha1, []).append(f)

        def update(book, f):
            book.filename = f.filename
            book.category = f.category
            book.mtime = f.mtime
            book.filesize = f.filesize
            # Create the thumbnail, in case it is missing for any reason
            self.cache.create_thumbnail(os.path.join(book_dir, f.filename),
                                        book.sha1)
            # Same for its metadata cache file (nothing done when up to date)
            if self.metadata is not None:
                self.metadata.request(book.sha1, os.path.join(book_dir, f.filename))

        def add_duplicates(book_file, group):
            for d in group:
                if d is book_file:
                    continue
                refreshed_duplicates.append(d)
                if d not in known_duplicates:
                    log.info("Duplicate PDF file: '%s' (book '%s')",
                             d.filename, book_file.filename)

        new_contents = []
        for sha1, group in groups.items():
            book = remaining.get(sha1)
            if book is None:
                new_contents.append(group)
                continue
            # Known content: the book stays on its file while it exists,
            # even if a copy is found first. Otherwise the book was moved (or
            # reappeared): its user settings are kept.
            f = next((f for f in group if f.filename == book.filename), group[0])
            if f.filename != book.filename:
                log.info("Book moved: '%s' -> '%s'", book.filename, f.filename)
                changed = True
            update(book, f)
            take(book)
            add_duplicates(f, group)

        for group in new_contents:
            # Same path but new content (file replaced in place): same book
            # entry, user settings kept, new sha1 and thumbnail
            book, f = next(((remaining_at(f.filename), f) for f in group
                            if remaining_at(f.filename)), (None, group[0]))
            if book:
                log.info("Book modified: '%s'", f.filename)
                take(book)
                book.sha1 = f.sha1
            else:
                log.info("New book: '%s'", f.filename)
                book = Book(book_dir)
                book.set_sha1(f.sha1)
                refreshed_booklist.append(book)
            changed = True
            update(book, f)
            add_duplicates(f, group)

        if set(refreshed_duplicates) != set(known_duplicates):
            changed = True

        # remaining contains all db entries not found in dir, thus removed.
        # let's keep those entry to keep user settings in case they reappears
        for b in remaining.values():
            if b.present:
                log.info("Book missing: '%s'", b.filename)
                changed = True
            b.mark_missing()
            refreshed_booklist.append(b)

        with self.lock:
            self.booklist = refreshed_booklist
            self.duplicates = refreshed_duplicates
            log.info("Directory scanned, save '%s'", self.dbfile)
            self.save_db()

        return changed

    @staticmethod
    def _list_pdf_files(book_dir, books, duplicates):
        """
        ([PdfFile], hashed): the PDF files of book_dir, and whether some
        files were hashed. The sha1 of a file which has the path and mtime of
        a known book or duplicate is not computed again.
        """
        files = []
        hashed = False
        # path -> known book (first), or duplicate
        known_files = {}
        for b in books:
            known_files.setdefault(b.filename, b)
        for d in duplicates:
            known_files.setdefault(d.filename, d)
        log.info("Scanning directory '%s' for PDF files", book_dir)
        for (dir, subdirs, filenames) in os.walk(book_dir):

            # Allow user to ignore some directories using a marker hidden
            # file, with their subdirectories (e.g. the trash)
            if os.path.exists(os.path.join(dir, IGNORE_MARKER)):
                subdirs[:] = []
                continue

            # Book category is first level directory name
            category = dir.replace(book_dir, '')[1:]
            category = category.split('/')[0]
            if category == '':
                category = 'Generals'

            for name in filenames:
                abspath = os.path.join(dir, name)
                if not abspath.lower().endswith("pdf"):
                    continue
                try:
                    st = os.stat(abspath)
                    mtime, filesize = st.st_mtime, st.st_size
                except OSError:
                    # removed in the meantime (or dangling symlink)
                    continue

                # Book object path are relative to BookDir path
                relpath = os.path.relpath(abspath, book_dir)

                known = known_files.get(relpath)
                # (the size too: a book transformed in place keeps its
                # modification time, see transform())
                if known and known.mtime == mtime and getattr(known, "filesize", filesize) == filesize:
                    sha1 = known.sha1
                else:
                    log.debug("Compute sha1 of %s", relpath)
                    try:
                        sha1 = sha1_file(abspath)
                    except OSError as e:
                        log.warning("Can not compute sha1 of %s: %s", relpath, e)
                        continue
                    hashed = True

                files.append(PdfFile(relpath, category, mtime, filesize, sha1))
        return files, hashed
