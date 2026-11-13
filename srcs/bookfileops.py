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
"""
Safe file operations in the book directory: paths are checked to stay in
the book directory, and a file is never overwritten.

Paths named 'relpath' are relative to the book directory, with '/'
separators, as the file names of the book database.
"""

import errno
import os
import posixpath

# A directory containing this file is ignored by the scan, with its
# subdirectories
IGNORE_MARKER = ".ebook-ignore-dir"

# Trash of the book directory, ignored by the scan
TRASH_DIR = "Trash"

# Category of the files at the root of the book directory
ROOT_CATEGORY = "Generals"


class BookFileError(Exception):
    """ A file operation in the book directory was refused, or failed """


def category_of(relpath):
    """ 'Science/sub/a.pdf' -> 'Science', 'a.pdf' -> 'Generals' """
    parts = relpath.split("/")
    return parts[0] if len(parts) > 1 else ROOT_CATEGORY


def check_relpath(relpath):
    """
    The normalized relpath of a PDF file of the book directory, or raise
    BookFileError: it must be relative, without '..' nor hidden component,
    and end with '.pdf'.
    """
    if not isinstance(relpath, str) or not relpath.strip():
        raise BookFileError("empty path")
    if "\0" in relpath or "\\" in relpath:
        raise BookFileError(f"invalid character in path: {relpath!r}")
    if relpath.startswith("/"):
        raise BookFileError(f"absolute path: {relpath!r}")
    parts = relpath.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            raise BookFileError(f"invalid path component in {relpath!r}")
        if part.startswith("."):
            raise BookFileError(f"hidden file or directory in {relpath!r}")
        if part != part.strip():
            raise BookFileError(f"leading or trailing space in {relpath!r}")
    if not parts[-1].lower().endswith(".pdf") or len(parts[-1]) <= len(".pdf"):
        raise BookFileError(f"not a PDF file name: {relpath!r}")
    return posixpath.normpath(relpath)


def _nearest_existing(path):
    while not os.path.lexists(path):
        path = os.path.dirname(path)
    return path


def check_inside(book_dir, relpath):
    """
    The absolute path of relpath, or raise BookFileError if its directory
    is not inside the book directory once symbolic links are resolved
    (e.g. a link to a directory outside of it).
    """
    abspath = os.path.join(book_dir, relpath)
    real_book_dir = os.path.realpath(book_dir)
    real_dir = os.path.realpath(_nearest_existing(os.path.dirname(abspath)))
    if os.path.commonpath([real_book_dir, real_dir]) != real_book_dir:
        raise BookFileError(f"{relpath!r} is outside of the book directory")
    return abspath


def is_ignored(book_dir, relpath):
    """ Whether relpath is in a directory ignored by the scan """
    parts = relpath.split("/")[:-1]
    if parts and parts[0] == TRASH_DIR:
        return True
    path = book_dir
    for part in [None] + parts:
        if part:
            path = os.path.join(path, part)
        if os.path.exists(os.path.join(path, IGNORE_MARKER)):
            return True
    return False


def move_no_replace(src, dst):
    """
    Move the file src to dst, creating the missing directories of dst, or
    raise BookFileError: dst is never overwritten. The name dst is first
    reserved (created exclusively), then replaced by src with an atomic
    rename, so that a file created at dst in the meantime is not lost.
    """
    if not os.path.isfile(src):
        raise BookFileError(f"no such file: {src}")
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise BookFileError(f"destination already exists: {dst}") from None
    except OSError as e:
        raise BookFileError(f"can not create {dst}: {e.strerror}") from None
    os.close(fd)
    try:
        os.replace(src, dst)
    except OSError as e:
        os.unlink(dst)
        if e.errno == errno.EXDEV:
            raise BookFileError(f"{src} and {dst} are not on the same file system") from None
        raise BookFileError(f"can not move {src} to {dst}: {e.strerror}") from None


def move_to_free_name(src, dst):
    """
    Move the file src to dst, or to 'name (2).pdf', 'name (3).pdf', ... if
    dst exists. Returns the destination used.
    """
    stem, ext = os.path.splitext(dst)
    for n in range(1, 1000):
        candidate = dst if n == 1 else f"{stem} ({n}){ext}"
        try:
            move_no_replace(src, candidate)
            return candidate
        except BookFileError:
            if not os.path.lexists(candidate) or not os.path.isfile(src):
                raise
    raise BookFileError(f"no free name for {dst}")


def ensure_trash(book_dir):
    """ Create the trash directory with its ignore marker, if needed """
    trash = os.path.join(book_dir, TRASH_DIR)
    os.makedirs(trash, exist_ok=True)
    marker = os.path.join(trash, IGNORE_MARKER)
    if not os.path.exists(marker):
        with open(marker, "w"):
            pass
    return trash
