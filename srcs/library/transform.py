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
The transformations of a book file in place (srcs/pdf/transformations.py):
the transformed file replaces it, the original goes to the trash, and can
be restored. Functions of a BookDir.
"""

import logging
import os
import posixpath
import re
import tempfile
from collections import namedtuple

import pymupdf

from srcs.common.files import sha1_file
from srcs.library import fileops as bookfileops
from srcs.library.caches import move_caches
from srcs.library.fileops import BookFileError
from srcs.library.operations import trash

log = logging.getLogger(__name__)

# A book whose file was replaced in place (transform(), restore_original()):
# its path, former and new sha1, the path in the trash of the file replaced,
# and the move of the pages (page n of the former file is page n +
# page_offset of the new one)
Transformed = namedtuple("Transformed", "filename old_sha1 new_sha1 trashed page_offset")

# Suffixes of the names in the trash of an original file replaced by its
# transformation, and of a transformed file replaced by its original
ORIGINAL_SUFFIX = " (original)"
TRANSFORMED_SUFFIX = " (transformed)"

def transform(bookdir, sha1, transformation):
    """
    Transform the PDF file of a book in place (srcs/pdf/transformations.py):
    the transformed file replaces it, with its modification time, and the
    original goes to the trash, 'Trash/<path> (original).pdf'. The book
    keeps its entry and user values, under the new sha1; its thumbnail
    and metadata analysis follow it when the transformation keeps the
    first page and the text, are made again otherwise. Returns a
    Transformed, or raises BookFileError (refused: missing book, copies
    of it in the library, failed check).
    """
    with bookdir._scan_lock:
        book = bookdir._present_book(sha1)
        if any(d.sha1 == sha1 for d in bookdir.duplicates):
            raise BookFileError(f"the book has copies in the library (duplicates): {book.filename}")
        src = os.path.join(bookdir.dirpath, book.filename)
        pages = _page_count(src)

        # Written next to it (same file system), under a name ignored by
        # the scan and the watcher (hidden, not a PDF)
        fd, tmpname = tempfile.mkstemp(prefix=".ebookonline-transform-", suffix=".tmp",
                                       dir=os.path.dirname(src))
        os.close(fd)
        try:
            transformation.apply(src, tmpname)
            transformation.check(src, tmpname)
            new_sha1 = sha1_file(tmpname)
            if bookdir.find_book_by_sha1(new_sha1) is not None:
                raise BookFileError(f"the transformed file is a known book: {new_sha1}")
            # the modification time of the original (a book of the
            # library since then, not a new one)
            st = os.stat(src)
            os.utime(tmpname, ns=(st.st_atime_ns, st.st_mtime_ns))
            original = trash(bookdir, book.filename, ORIGINAL_SUFFIX)
            os.replace(tmpname, src)
        finally:
            if os.path.exists(tmpname):
                os.unlink(tmpname)

        result = _swap(bookdir, book, new_sha1, transformation.keeps_first_page,
                             transformation.keeps_text, original,
                             _page_count(src) - pages)
        log.info("Book transformed (%s): '%s' %s -> %s, original: '%s'",
                 transformation.name, book.filename, sha1, new_sha1, original)
    return result


def original_in_trash(bookdir, sha1):
    """
    The path in the trash of the original of the last transformation of
    a book ('Trash/<path> (original).pdf', or '... (original) (N).pdf'
    for the latest of several), or None
    """
    book = bookdir.find_book_by_sha1(sha1)
    if book is None or not book.present:
        return None
    stem = posixpath.splitext(book.filename)[0]
    prefix = posixpath.join(bookfileops.TRASH_DIR, stem + ORIGINAL_SUFFIX)
    found = []
    for trashed in bookfileops.list_trash(bookdir.dirpath):
        relpath = trashed.filename
        if relpath == prefix + ".pdf":
            found.append((1, relpath))
        else:
            m = re.fullmatch(re.escape(prefix) + r" \((\d+)\)\.pdf", relpath)
            if m:
                found.append((int(m.group(1)), relpath))
    return max(found)[1] if found else None


def restore_original(bookdir, sha1):
    """
    Undo the last transformation of a book: its original (see
    original_in_trash()) takes the place of the file again, which goes to
    the trash, 'Trash/<path> (transformed).pdf'. The book keeps its entry
    and user values, under the sha1 of the original. Returns a
    Transformed, or raises BookFileError.
    """
    with bookdir._scan_lock:
        book = bookdir._present_book(sha1)
        original = original_in_trash(bookdir, sha1)
        if original is None:
            raise BookFileError(f"no original in the trash: {book.filename}")
        if any(d.sha1 == sha1 for d in bookdir.duplicates):
            raise BookFileError(f"the book has copies in the library (duplicates): {book.filename}")
        path = os.path.join(bookdir.dirpath, book.filename)
        src = bookfileops.check_inside(bookdir.dirpath, original)
        old_sha1 = sha1_file(src)
        if bookdir.find_book_by_sha1(old_sha1) is not None:
            raise BookFileError(f"the original is a known book: {old_sha1}")
        pages = _page_count(path)
        transformed = trash(bookdir, book.filename, TRANSFORMED_SUFFIX)
        bookfileops.move_no_replace(src, path)
        result = _swap(bookdir, book, old_sha1, False, False, transformed,
                             _page_count(path) - pages)
        log.info("Book restored: '%s' %s -> %s, transformed: '%s'",
                 book.filename, sha1, old_sha1, transformed)
    return result


def _page_count(path):
    try:
        with pymupdf.open(path) as doc:
            return doc.page_count
    except Exception as e:
        raise BookFileError(f"can not read the PDF file: {e}") from None


def _swap(bookdir, book, new_sha1, keeps_first_page, keeps_text, trashed, page_offset):
    """
    The entry of a book whose file was replaced: its new sha1 and size
    (same path, same modification time), its caches; book.db saved (the
    watcher then finds nothing to do). Returns a Transformed.
    """
    path = os.path.join(bookdir.dirpath, book.filename)
    old_sha1 = book.sha1
    with bookdir.lock:
        book.sha1 = new_sha1
        book.filesize = os.stat(path).st_size
        book.mtime = os.stat(path).st_mtime
    move_caches(bookdir, old_sha1, new_sha1, path, keeps_first_page, keeps_text)
    bookdir.save_db()
    return Transformed(book.filename, old_sha1, new_sha1, trashed, page_offset)
