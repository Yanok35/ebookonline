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
The services of the book directory, made from the configuration
(srcs/config.py): for the server (app/__init__.py) and the command line
(srcs/cli.py).
"""

from srcs.access import can_write_dir
from srcs.book import BookDir
from srcs.cache import Cache


def make_cache(config, workers=None):
    """
    The cache of the thumbnails (creates the cache directory if missing),
    writable when its directory can be written. workers: the number of
    thumbnail processes, None for the default, 0 for none (the command
    line: thumbnails made in the process itself).
    """
    cache = Cache.get_instance(config["CACHE_DIR"], workers=workers)
    # No thumbnail generation which would fail
    cache.writable = can_write_dir(config["CACHE_DIR"])
    return cache


def make_bookdir(config, cache, read_only=False):
    """ The book directory, its last known book list (book.db) read, not scanned """
    bookdir = BookDir(config["BOOK_DB"], cache, read_only=read_only)
    bookdir.open(config["BOOK_DIR"])
    return bookdir
