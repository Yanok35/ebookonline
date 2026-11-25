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

    # Forms (Flask-WTF): the CSRF token is valid as long as the session,
    # an admin page may stay open for hours before being submitted.
    WTF_CSRF_TIME_LIMIT = None

    BOOK_DIR = os.path.join(basedir, "books")
    CACHE_DIR = os.path.join(basedir, "cache")

    # Watch BOOK_DIR (inotify) and update the book database when PDF files
    # are added, moved or removed, once the directory has been quiet for
    # BOOK_DIR_WATCH_DELAY seconds.
    BOOK_DIR_WATCH = True
    BOOK_DIR_WATCH_DELAY = 2.0

    # Analyse the PDF files in background processes, to suggest their
    # metadata (title, authors, editor, year, ISBN) in the admin pages: the
    # results are kept in CACHE_DIR (<sha1>.meta.json.gz). METADATA_WORKERS
    # processes (0: half of the processors), at the nice level METADATA_NICE
    # (0: same priority as the server). More processes analyse a large
    # library sooner, at the first start, but take more memory.
    METADATA_ANALYSIS = True
    METADATA_WORKERS = 1
    METADATA_NICE = 10

    # Name of the PDF files after their metadata (book.db), proposed on the
    # book page: {title}, {subtitle}, {author}, {authors}, {author_sort},
    # {editor}, {year}, {isbn}; a missing value is left out with its
    # parentheses or separator. A file name only, without directory. The
    # subtitle makes the file name searchable in the library (the search
    # is on the file names). See docs/technote-file-naming.md.
    FILENAME_PATTERN = "{title} {subtitle} - {author_sort}, {year}"

    # Theme of the reader: "dark" (warm dark browns) or "light" (the beige
    # look of the other pages); any other value is "dark".
    READER_THEME = "dark"

    # Following are in current directory
    BOOK_DB = "book.db"
    STATE_FILE = "reader_states.json"
    # The data of the users (their notes in the margin of the books): a
    # versioned JSON file, as book.db (see docs/technote-userdata.md)
    USERDATA_DB = "userdata.db"
    # Journal of the reader events: one JSON line per saved position (the
    # base of the reading history: sessions, reading time). Empty: no journal.
    READER_EVENTS_FILE = "reader_events.jsonl"

    # Largest request body, in bytes: the image of a cover page (20 MiB at
    # most, see srcs/pdfcover.py), with the other fields of its form
    MAX_CONTENT_LENGTH = 21 * 1024 * 1024
    # Largest book uploaded from the library page (drag and drop), in
    # bytes: it goes to BOOK_DIR/Incoming
    UPLOAD_MAX_SIZE = 500 * 1024 * 1024

    # Logs on stderr (journald under systemd), from this level: DEBUG,
    # INFO, WARNING, ERROR
    LOG_LEVEL = "INFO"

    # Enable real IP coming before the Reverse proxy (this will allow to
    # identify suspicious scan with fail2ban)
    BEHIND_REVERSE_PROXY = True