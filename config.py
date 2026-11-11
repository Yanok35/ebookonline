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

from __future__ import unicode_literals

import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    """
    This class contains application default configuration. They can be
    overriden using:
     - `instance/config.py` (e.g. installed on production server),
     - environment variables prefixed with `EBOOKONLINE_`.
    """

    # Required: the application refuses to start without it.
    SECRET_KEY = None

    # {username: password hash}, hashes are generated with
    # werkzeug.security.generate_password_hash() (see README).
    CREDENTIALS = {}

    BOOK_DIR = os.path.join(basedir, "books")
    CACHE_DIR = os.path.join(basedir, "cache")

    # Watch BOOK_DIR (inotify) and update the book database when PDF files
    # are added, moved or removed, once the directory has been quiet for
    # BOOK_DIR_WATCH_DELAY seconds.
    BOOK_DIR_WATCH = True
    BOOK_DIR_WATCH_DELAY = 2.0

    # Following are in current directory
    BOOK_DB = "book.db"
    STATE_FILE = "reader_states.json"

    # Enable real IP coming before the Reverse proxy (this will allow to
    # identify suspicious scan with fail2ban)
    BEHIND_REVERSE_PROXY = True