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

""" A book of the library (an entry of book.db), and a PDF file found by a scan """

import os
from collections import namedtuple

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

        # - empty after scan_dir; never set from the suggestions of
        #   srcs/metadata without the user
        self.title = ""
        self.subtitle = ""
        self.authors = []
        self.year = 0
        self.editor = ""
        self.isbn = ""
        self.tags = ""
        # the user has reviewed (and validated) the metadata
        self.meta_reviewed = False

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
            "title": self.title,
            "subtitle": self.subtitle,
            "authors": self.authors,
            "editor": self.editor,
            "year": self.year,
            "isbn": self.isbn,
            "meta_reviewed": self.meta_reviewed,
            "bookmarked": self.bookmarked,
        }
        return d
