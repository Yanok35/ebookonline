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
import shutil
import sys
import tempfile
import threading
from collections import namedtuple
from threading import Thread

from srcs import bookfileops
from srcs.bookfileops import IGNORE_MARKER, BookFileError
from srcs.cache import Cache
from srcs.cache import sha1_file
from srcs.search import fuzzy_search

import os
import posixpath

# Schema version of the book database file (book.db). A file without version
# is version 0. Increment it when the file format changes, and append the
# conversion from the previous version to _MIGRATIONS.
DB_VERSION = 2

# Oldest schema version whose code can read a book.db of version DB_VERSION
# (saved in the file as 'min_reader_version'). Unchanged by a compatible
# change, e.g. a new key, which older code ignores; set to DB_VERSION by an
# incompatible one, e.g. a key whose type or meaning changes.
DB_MIN_READER_VERSION = 1


class BookDbVersionError(RuntimeError):
    """ book.db was written by a newer version of ebookonline """


def _migrate_v0(db):
    """ 0 -> 1: the 'version' key is added, nothing else changes """
    return db


def _migrate_v1(db):
    """ 1 -> 2: the duplicate files are saved """
    db["duplicates"] = []
    return db


# _MIGRATIONS[n] converts the JSON content of a version n file to version n+1
_MIGRATIONS = [_migrate_v0, _migrate_v1]
assert len(_MIGRATIONS) == DB_VERSION


def migrate_db(db):
    """ Convert the JSON content of an older book.db to DB_VERSION """
    for migrate in _MIGRATIONS[db.get("version", 0):]:
        db = migrate(db)
    db["version"] = DB_VERSION
    return db


# A PDF file found in the book directory
PdfFile = namedtuple("PdfFile", "filename category mtime filesize sha1")


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
            "editor": self.editor,
            "year": self.year,
            "isbn": self.isbn,
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
        # Other files having the content of a book ([PdfFile])
        self.duplicates = []
        self.cache = cache
        self.dbfile = dbfile
        self.dirpath = None

        self.lock = threading.RLock()
        self._scan_lock = threading.Lock()
        self._loaded = False

        # book.db written by a newer version of ebookonline, but readable by
        # this one: it is never written, changes are kept in memory only.
        self.read_only = False
        # Schema version of the book.db file, when read-only
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
            print("Warning: dbfile is empty")
            return

        booklist = []
        with open(self.dbfile, "r") as f:
            inp = json.load(f)

            # Rewriting a newer file would silently drop the data this
            # version does not know (e.g. after a rollback of the server):
            # it is opened read-only, if this version can read it.
            version = inp.get("version", 0)
            if version > DB_VERSION:
                # missing: only its own version is known to read it
                min_reader = inp.get("min_reader_version", version)
                if min_reader > DB_VERSION:
                    raise BookDbVersionError(
                        f"{self.dbfile}: schema version {version} can only "
                        f"be read by schema version {min_reader} or newer, "
                        f"this is version {DB_VERSION}: upgrade ebookonline")
                print(f"*** Warning: {self.dbfile}: schema version {version} "
                      f"is newer than the supported version {DB_VERSION}: "
                      f"read-only, changes are kept in memory only")
                self.read_only = True
                self.db_version = version
            if version < DB_VERSION:
                inp = migrate_db(inp)

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

                new.editor = b.get("editor", "")
                new.year = b.get("year", 0)
                new.isbn = b.get("isbn", "")

                booklist.append(new)

        duplicates = [PdfFile(**d) for d in inp.get("duplicates", [])]

        with self.lock:
            self.booklist = booklist
            self.duplicates = duplicates

        if version < DB_VERSION:
            # Keep the file of the previous version, the first time only
            backup = f"{self.dbfile}.v{version}.bak"
            if not os.path.exists(backup):
                shutil.copy2(self.dbfile, backup)
            print(f"Migrate {self.dbfile} from schema version {version} to "
                  f"{DB_VERSION} (backup: {backup})")
            self.save_db()

    def to_json(self):
        d = {
            'version': DB_VERSION,
            'min_reader_version': DB_MIN_READER_VERSION,
            'dirpath': self.dirpath,
            'booklist': [ b.to_json() for b in self.booklist ],
            'duplicates': [ d._asdict() for d in self.duplicates ],
        }
        return d

    def save_db(self):
        """
        Write the database in a temporary file, then replace the previous
        one, so that an interruption can not leave a truncated JSON file.
        Nothing is written when read-only.
        """
        if self.read_only:
            return
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

    def get_duplicates(self):
        """
        {sha1: [PdfFile]}: for each book having duplicates, the other files
        with the same content, sorted by path.
        """
        duplicates = {}
        for d in sorted(self.duplicates, key=lambda d: d.filename):
            duplicates.setdefault(d.sha1, []).append(d)
        return duplicates

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

    # File operations in the book directory. They hold the scan lock, move
    # the file, then rescan the directory: the book list follows the same
    # rules as for a change made outside of the server (e.g. a duplicate
    # replaces a book moved to the trash). The rescan hashes no file again,
    # a move keeps the modification time of the file.

    def __present_book(self, sha1):
        book = self.find_book_by_sha1(sha1)
        if book is None:
            raise BookFileError(f"unknown book: {sha1}")
        if not book.present or not os.path.isfile(os.path.join(self.dirpath, book.filename)):
            raise BookFileError(f"the file of the book is missing: {book.filename}")
        return book

    def move_book(self, sha1, relpath):
        """
        Move or rename the file of a book to relpath, relative to the book
        directory, creating the missing directories. The book keeps its user
        settings. Returns the new path of the book, or raises BookFileError:
        invalid path, destination which exists, is outside of the book
        directory or ignored by the scan, missing book file, ...
        """
        relpath = bookfileops.check_relpath(relpath)
        if bookfileops.is_ignored(self.dirpath, relpath):
            raise BookFileError(f"{relpath!r} is ignored by the scan")
        dst = bookfileops.check_inside(self.dirpath, relpath)

        with self._scan_lock:
            book = self.__present_book(sha1)
            if relpath == book.filename:
                return relpath
            bookfileops.move_no_replace(os.path.join(self.dirpath, book.filename), dst)
            print("Book moved: '%s' -> '%s'" % (book.filename, relpath))
            # Known at its new path: the rescan does not hash it again
            with self.lock:
                book.filename = relpath
                book.category = bookfileops.category_of(relpath)
            self.__rescan()
        return relpath

    def rename_book(self, sha1, name):
        """
        Rename the file of a book, in its directory ('.pdf' is appended if
        missing). Returns the new path of the book, see move_book().
        """
        if "/" in name:
            raise BookFileError(f"invalid file name: {name!r}")
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        book = self.find_book_by_sha1(sha1)
        if book is None:
            raise BookFileError(f"unknown book: {sha1}")
        return self.move_book(sha1, posixpath.join(posixpath.dirname(book.filename), name))

    def move_book_to_category(self, sha1, category):
        """
        Move the file of a book to a category: an existing first level
        directory (see bookfileops.list_categories()), or the root of the
        book directory for ''. Returns the new path of the book, see
        move_book().
        """
        if category and category not in bookfileops.list_categories(self.dirpath):
            raise BookFileError(f"unknown category: {category!r}")
        book = self.find_book_by_sha1(sha1)
        if book is None:
            raise BookFileError(f"unknown book: {sha1}")
        name = posixpath.basename(book.filename)
        return self.move_book(sha1, posixpath.join(category, name) if category else name)

    def trash_book(self, sha1):
        """
        Move the file of a book to the trash, at the same path in it (e.g.
        Trash/Science/a.pdf, or 'a (2).pdf' if it exists). The book is kept,
        missing, and gets its user settings back if the file is moved back
        to the book directory; a duplicate replaces it if any. Returns the
        path of the file in the trash, or raises BookFileError.
        """
        with self._scan_lock:
            book = self.__present_book(sha1)
            trashed = self.__trash(book.filename)
            print("Book trashed: '%s' -> '%s'" % (book.filename, trashed))
            self.__rescan()
        return trashed

    def trash_duplicate(self, relpath):
        """
        Move a duplicate file to the trash, see trash_book(). Returns the
        path of the file in the trash, or raises BookFileError.
        """
        with self._scan_lock:
            if relpath not in (d.filename for d in self.duplicates) \
                    or not os.path.isfile(os.path.join(self.dirpath, relpath)):
                raise BookFileError(f"not a duplicate file: {relpath!r}")
            trashed = self.__trash(relpath)
            print("Duplicate trashed: '%s' -> '%s'" % (relpath, trashed))
            self.__rescan()
        return trashed

    def __trash(self, relpath):
        bookfileops.ensure_trash(self.dirpath)
        dst = bookfileops.check_inside(self.dirpath, posixpath.join(bookfileops.TRASH_DIR, relpath))
        dst = bookfileops.move_to_free_name(os.path.join(self.dirpath, relpath), dst)
        return os.path.relpath(dst, self.dirpath).replace(os.sep, "/")

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
            known_duplicates = list(self.duplicates)
        refreshed_booklist = []
        refreshed_duplicates = []
        changed = False

        def take(book):
            remaining.remove(book)
            refreshed_booklist.append(book)

        # 1. List the PDF files of the directory, with their sha1. Only new
        #    or modified files are hashed.
        files, hashed = self.__list_pdf_files(book_dir, remaining, known_duplicates)
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

        def add_duplicates(book_file, group):
            for d in group:
                if d is book_file:
                    continue
                refreshed_duplicates.append(d)
                if d not in known_duplicates:
                    print("*** Warning: duplicate PDF file: '%s' (book '%s')"
                          % (d.filename, book_file.filename))

        new_contents = []
        for sha1, group in groups.items():
            book = next((b for b in remaining if b.sha1 == sha1), None)
            if book is None:
                new_contents.append(group)
                continue
            # Known content: the book stays on its file while it exists,
            # even if a copy is found first. Otherwise the book was moved (or
            # reappeared): its user settings are kept.
            f = next((f for f in group if f.filename == book.filename), group[0])
            if f.filename != book.filename:
                print("Book moved: '%s' -> '%s'" % (book.filename, f.filename))
                changed = True
            update(book, f)
            take(book)
            add_duplicates(f, group)

        for group in new_contents:
            # Same path but new content (file replaced in place): same book
            # entry, user settings kept, new sha1 and thumbnail
            book, f = next(((b, f) for f in group for b in remaining
                            if b.filename == f.filename), (None, group[0]))
            if book:
                print("Book modified: '%s'" % f.filename)
                book.sha1 = f.sha1
            else:
                print("New book: '%s'" % f.filename)
                book = Book(book_dir)
                book.set_sha1(f.sha1)
                remaining.append(book)
            changed = True
            update(book, f)
            take(book)
            add_duplicates(f, group)

        if set(refreshed_duplicates) != set(known_duplicates):
            changed = True

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
            self.duplicates = refreshed_duplicates
            print("Directory db fully parsed. Save JSON db file...")
            self.save_db()

        return changed

    @staticmethod
    def __list_pdf_files(book_dir, books, duplicates):
        """
        ([PdfFile], hashed): the PDF files of book_dir, and whether some
        files were hashed. The sha1 of a file which has the path and mtime of
        a known book or duplicate is not computed again.
        """
        files = []
        hashed = False
        print("Scanning directory %s for PDF files..." % book_dir)
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
                    mtime = os.path.getmtime(abspath)
                    filesize = os.stat(abspath).st_size
                except OSError:
                    # removed in the meantime (or dangling symlink)
                    continue

                # Book object path are relative to BookDir path
                relpath = os.path.relpath(abspath, book_dir)

                known = next((b for b in books if b.filename == relpath), None) \
                    or next((d for d in duplicates if d.filename == relpath), None)
                if known and known.mtime == mtime:
                    sha1 = known.sha1
                else:
                    print("Compute sha1 for %s..." % name, end="")
                    sys.stdout.flush()
                    try:
                        sha1 = sha1_file(abspath)
                    except OSError as e:
                        print("failed: %s" % e)
                        continue
                    print("done")
                    hashed = True

                files.append(PdfFile(relpath, category, mtime, filesize, sha1))
        return files, hashed
