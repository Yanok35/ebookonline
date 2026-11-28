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
The operations on the files of the book directory: move, rename, to the
trash and back, add (upload). Functions of a BookDir.

File operations in the book directory. They hold the scan lock, move
the file, then rescan the directory: the book list follows the same
rules as for a change made outside of the server (e.g. a duplicate
replaces a book moved to the trash). The rescan hashes no file again,
a move keeps the modification time of the file. A move or a rename of
a book only updates this book: nothing else changes.
"""

import logging
import os
import posixpath
import shutil
import tempfile

from srcs.library import fileops as bookfileops
from srcs.library.fileops import BookFileError, BookFileExists
from srcs.pdf import PDF_MAGIC

log = logging.getLogger(__name__)

# The files which can be uploaded, by extension: the beginning of their
# content (in their first 1024 bytes; an EPUB file is a ZIP archive)
UPLOADS = {".pdf": PDF_MAGIC, ".epub": b"PK\x03\x04"}

def incoming_path(bookdir, filename):
    """
    The path in INCOMING_DIR of an uploaded file, from its name (the
    name only: a path is the one of the client), or raise BookFileError
    (invalid name, not a PDF or EPUB file name)
    """
    name = posixpath.basename(filename.replace("\\", "/")).strip().lstrip(".").strip()
    return bookfileops.check_relpath(posixpath.join(bookfileops.INCOMING_DIR, name),
                                     tuple(UPLOADS))


def move_book(bookdir, sha1, relpath):
    """
    Move or rename the file of a book to relpath, relative to the book
    directory, creating the missing directories. The book keeps its user
    settings. Returns the new path of the book, or raises BookFileError:
    invalid path, destination which exists, is outside of the book
    directory or ignored by the scan, missing book file, ...
    """
    relpath = bookfileops.check_relpath(relpath)
    if bookfileops.is_ignored(bookdir.dirpath, relpath):
        raise BookFileError(f"{relpath!r} is ignored by the scan")
    dst = bookfileops.check_inside(bookdir.dirpath, relpath)

    with bookdir._scan_lock:
        book = bookdir._present_book(sha1)
        if relpath == book.filename:
            return relpath
        bookfileops.move_no_replace(os.path.join(bookdir.dirpath, book.filename), dst)
        log.info("Book moved: '%s' -> '%s'", book.filename, relpath)
        # Only this book changes (same content, thumbnail and metadata):
        # no rescan of the whole directory, which takes a while for a
        # large library. The other changes of the directory, if any,
        # are found by the watcher, or by the next scan.
        st = os.stat(dst)
        with bookdir.lock:
            book.filename = relpath
            book.category = bookfileops.category_of(relpath)
            book.mtime, book.filesize = st.st_mtime, st.st_size
        bookdir.save_db()
    return relpath


def rename_book(bookdir, sha1, name):
    """
    Rename the file of a book, in its directory ('.pdf' is appended if
    missing). Returns the new path of the book, see move_book().
    """
    if "/" in name:
        raise BookFileError(f"invalid file name: {name!r}")
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    book = bookdir.find_book_by_sha1(sha1)
    if book is None:
        raise BookFileError(f"unknown book: {sha1}")
    return move_book(bookdir, sha1, posixpath.join(posixpath.dirname(book.filename), name))


def move_book_to_category(bookdir, sha1, category):
    """
    Move the file of a book to a category: an existing first level
    directory (see bookfileops.list_categories()), or the root of the
    book directory for ''. Returns the new path of the book, see
    move_book().
    """
    if category and category not in bookfileops.list_categories(bookdir.dirpath):
        raise BookFileError(f"unknown category: {category!r}")
    book = bookdir.find_book_by_sha1(sha1)
    if book is None:
        raise BookFileError(f"unknown book: {sha1}")
    name = posixpath.basename(book.filename)
    return move_book(bookdir, sha1, posixpath.join(category, name) if category else name)


def trash_book(bookdir, sha1):
    """
    Move the file of a book to the trash, at the same path in it (e.g.
    Trash/Science/a.pdf, or 'a (2).pdf' if it exists). The book is kept,
    missing, and gets its user settings back if the file is moved back
    to the book directory; a duplicate replaces it if any. Returns the
    path of the file in the trash, or raises BookFileError.
    """
    with bookdir._scan_lock:
        book = bookdir._present_book(sha1)
        trashed = trash(bookdir, book.filename)
        log.info("Book trashed: '%s' -> '%s'", book.filename, trashed)
        bookdir._rescan()
    return trashed


def trash_duplicate(bookdir, relpath):
    """
    Move a duplicate file to the trash, see trash_book(). Returns the
    path of the file in the trash, or raises BookFileError.
    """
    bookdir._check_writable()
    with bookdir._scan_lock:
        if relpath not in (d.filename for d in bookdir.duplicates) \
                or not os.path.isfile(os.path.join(bookdir.dirpath, relpath)):
            raise BookFileError(f"not a duplicate file: {relpath!r}")
        trashed = trash(bookdir, relpath)
        log.info("Duplicate trashed: '%s' -> '%s'", relpath, trashed)
        bookdir._rescan()
    return trashed


def restore_from_trash(bookdir, relpath):
    """
    Move a file of the trash (Trash/...) back to its original path in
    the book directory (never overwriting a file). A book gets its user
    settings back. Returns the restored path, or raises BookFileError.
    """
    bookdir._check_writable()
    prefix = bookfileops.TRASH_DIR + "/"
    relpath = bookfileops.check_relpath(relpath)
    if not relpath.startswith(prefix):
        raise BookFileError(f"not in the trash: {relpath!r}")
    original = relpath[len(prefix):]
    if bookfileops.is_ignored(bookdir.dirpath, original):
        raise BookFileError(f"{original!r} is ignored by the scan")
    src = bookfileops.check_inside(bookdir.dirpath, relpath)
    dst = bookfileops.check_inside(bookdir.dirpath, original)

    with bookdir._scan_lock:
        bookfileops.move_no_replace(src, dst)
        log.info("Restored from the trash: '%s'", original)
        bookdir._rescan()
    return original


def incoming_exists(bookdir, filename):
    """ Whether the file of this name is already in INCOMING_DIR (False: invalid name) """
    try:
        relpath = incoming_path(bookdir, filename)
    except BookFileError:
        return False
    return os.path.lexists(os.path.join(bookdir.dirpath, relpath))


def add_book(bookdir, stream, filename):
    """
    Add the file read from stream (an upload) to the book directory, as
    INCOMING_DIR/<name of filename>, never replacing a file. A PDF file is
    a book: the directory is rescanned, it is in the list at once. An
    EPUB file is only stored (the library has PDF files only). Returns
    its path, or raises BookFileError (not a PDF or EPUB file, invalid
    name), BookFileExists (a file of this name in INCOMING_DIR).
    """
    relpath = incoming_path(bookdir, filename)
    name = posixpath.basename(relpath)
    ext = posixpath.splitext(name)[1].lower()
    dst = bookfileops.check_inside(bookdir.dirpath, relpath)
    if os.path.lexists(dst):
        raise BookFileExists(f"already in {bookfileops.INCOMING_DIR}: {name!r}")
    # checked before anything is created (the readers of PDF accept a
    # header in the first 1024 bytes)
    head = stream.read(1024)
    magic = UPLOADS[ext]
    if (magic not in head) if ext == ".pdf" else not head.startswith(magic):
        raise BookFileError(f"not a {ext.lstrip('.').upper()} file: {name!r}")
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
    except OSError as e:
        raise BookFileError(f"can not create {bookfileops.INCOMING_DIR}: {e.strerror}") from None

    # Written next to its destination (same file system), under a name
    # ignored by the scan and the watcher (hidden, not a PDF); not under
    # the scan lock: the copy of a large file takes time
    fd, tmpname = tempfile.mkstemp(prefix=".ebookonline-upload-", suffix=".tmp",
                                   dir=os.path.dirname(dst))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(head)
            shutil.copyfileobj(stream, f, 1024 * 1024)
        # readable as a file copied there (mkstemp: by its owner only)
        os.chmod(tmpname, 0o644)
        with bookdir._scan_lock:
            try:
                bookfileops.move_no_replace(tmpname, dst)
            except BookFileError:
                if os.path.lexists(dst):
                    # (uploaded meanwhile)
                    raise BookFileExists(f"already in {bookfileops.INCOMING_DIR}: {name!r}") from None
                raise
            log.info("File added: '%s'", relpath)
            if ext == ".pdf":
                bookdir._rescan()
    finally:
        if os.path.exists(tmpname):
            os.unlink(tmpname)
    return relpath


def trash(bookdir, relpath, suffix=""):
    """ Move a file to the trash, at its path in it (with suffix before '.pdf') """
    bookfileops.ensure_trash(bookdir.dirpath)
    stem, ext = posixpath.splitext(relpath)
    dst = bookfileops.check_inside(bookdir.dirpath,
                                   posixpath.join(bookfileops.TRASH_DIR, stem + suffix + ext))
    dst = bookfileops.move_to_free_name(os.path.join(bookdir.dirpath, relpath), dst)
    return os.path.relpath(dst, bookdir.dirpath).replace(os.sep, "/")
