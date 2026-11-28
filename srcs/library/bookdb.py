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
The book database file, book.db (see docs/technote-bookdb.md): its schema
version, the migrations from the older ones, read and written.
"""

import json

from srcs.common.files import atomic_write
from srcs.common.versioned import file_version, migrate
from srcs.library.book import Book, PdfFile

# Schema version of the book database file (book.db). A file without version
# is version 0. Increment it when the file format changes, and append the
# conversion from the previous version to _MIGRATIONS.
DB_VERSION = 4

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


def _migrate_v2(db):
    """ 2 -> 3: title, authors and meta_reviewed are added to the books """
    for b in db["booklist"]:
        b.setdefault("title", "")
        b.setdefault("authors", [])
        b.setdefault("meta_reviewed", False)
    return db


def _migrate_v3(db):
    """ 3 -> 4: subtitle is added to the books """
    for b in db["booklist"]:
        b.setdefault("subtitle", "")
    return db


# _MIGRATIONS[n] converts the JSON content of a version n file to version n+1
_MIGRATIONS = [_migrate_v0, _migrate_v1, _migrate_v2, _migrate_v3]
assert len(_MIGRATIONS) == DB_VERSION


def migrate_db(db):
    """ Convert the JSON content of an older book.db to DB_VERSION """
    return migrate(db, _MIGRATIONS)


def read(dbfile, dirpath):
    """
    (books, duplicates, version) of the file dbfile, of the book directory
    dirpath: [Book], [PdfFile], and the schema version of the file (an
    older one migrated, a newer one read as it is). Raises
    BookDbVersionError when this code can not read it.
    """
    with open(dbfile, "r") as f:
        inp = json.load(f)

    # Rewriting a newer file would silently drop the data this version does
    # not know (e.g. after a rollback of the server): it is opened
    # read-only (see BookDir.load_db()), if this version can read it.
    version = file_version(inp, dbfile, DB_VERSION, BookDbVersionError)
    if version < DB_VERSION:
        inp = migrate_db(inp)

    books = []
    for b in inp['booklist']:
        # Books whose PDF is missing are kept (marked as missing by
        # set_filename), to restore their settings if they come back.
        new = Book(dirpath)
        new.set_sha1(b["sha1"])
        new.set_filename(b["filename"])
        new.set_category(b["category"])

        if "tags" in b.keys():
            new.set_tags(b["tags"])

        if "bookmarked" in b.keys():
            new.bookmarked = b["bookmarked"]

        new.title = b.get("title", "")
        new.subtitle = b.get("subtitle", "")
        new.authors = list(b.get("authors", []))
        new.meta_reviewed = b.get("meta_reviewed", False)
        new.editor = b.get("editor", "")
        new.year = b.get("year", 0)
        new.isbn = b.get("isbn", "")

        books.append(new)

    duplicates = [PdfFile(**d) for d in inp.get("duplicates", [])]
    return books, duplicates, version


def to_json(dirpath, books, duplicates):
    """ The content of book.db """
    return {
        'version': DB_VERSION,
        'min_reader_version': DB_MIN_READER_VERSION,
        'dirpath': dirpath,
        'booklist': [b.to_json() for b in books],
        'duplicates': [d._asdict() for d in duplicates],
    }


def write(dbfile, content):
    """
    Write book.db: in a temporary file, then renamed, so that an
    interruption can not leave a truncated JSON file
    """
    s = json.dumps(content, default=lambda o: o.__dict__, indent=2)
    atomic_write(dbfile, lambda f: f.write(s), fsync=True, prefix=".book_db_")
