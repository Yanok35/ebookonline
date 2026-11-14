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
Write access checks, done at startup: the server runs read-only when it can
not write where it needs to.
"""

import os
import tempfile


def can_write_dir(dirpath):
    """
    True when a file can be created (and removed) in the directory dirpath.

    A file is actually created: os.access() does not know of every reason
    to refuse a write (ACL, NFS root squashing, ...). The file name starts
    with a dot and is not a PDF, it is ignored by the directory scan.
    """
    try:
        fd, name = tempfile.mkstemp(prefix=".ebookonline-write-test-",
                                    dir=dirpath)
    except OSError:
        return False
    os.close(fd)
    try:
        os.unlink(name)
    except OSError:
        return False
    return True


def file_dir(path):
    """ The directory of a file path ('book.db': the current directory) """
    return os.path.dirname(os.path.abspath(path))


def check_write_access(book_dir, book_db, state_file):
    """
    Check that the server can write in the book directory (file operations
    of the admin pages), and in the directories of the book database and of
    the reader states (both are written to a temporary file, then renamed).

    Returns the list of the problems found, as messages; empty when every
    write is possible.
    """
    problems = []
    for description, dirpath in [
        ("le répertoire des livres", book_dir),
        (f"le répertoire de la base des livres ({os.path.basename(book_db)})",
         file_dir(book_db)),
        (f"le répertoire des positions de lecture ({os.path.basename(state_file)})",
         file_dir(state_file)),
    ]:
        if not can_write_dir(dirpath):
            problems.append(f"Écriture impossible dans {description} : {dirpath}")
    return problems
