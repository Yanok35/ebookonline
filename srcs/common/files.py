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

""" Files: written atomically, removed quietly, hashed """

import hashlib
import os
import tempfile


def atomic_write(path, write, binary=False, fsync=False, prefix=".ebookonline-"):
    """
    Write the file path by write(f), f a file opened in its directory
    (text, UTF-8, or binary), under a temporary name (prefix, hidden), then
    renamed: path is never left half written. fsync: written to the disk
    before the renaming.
    """
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmpname = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=directory)
    try:
        with (os.fdopen(fd, "wb") if binary else os.fdopen(fd, "w", encoding="utf-8")) as f:
            write(f)
            if fsync:
                f.flush()
                os.fsync(f.fileno())
        os.replace(tmpname, path)
    finally:
        if os.path.exists(tmpname):
            os.unlink(tmpname)


def remove_quietly(path):
    """ Remove a file, if it exists """
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def sha1_file(filename):
    """ The SHA-1 of the content of a file, in hexadecimal """
    with open(filename, 'rb') as fd_in:
        digest = hashlib.file_digest(fd_in, "sha1")
        return digest.hexdigest()
