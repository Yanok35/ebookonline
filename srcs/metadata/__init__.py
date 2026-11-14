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
Metadata of the books (title, authors, editor, year, ISBN), found in their
PDF files, as suggestions for the user. See
docs/technote-metadata-extract-&-analysis.md.

- extract: raw data read from a PDF file (metadata, text of the key pages)
- analyse: candidate values found in the raw data, and their consolidation
  into suggestions, with a score
- store: the cache file of a book (CACHE_DIR/<sha1>.meta.json.gz)
- isbn, names, publishers, text: the rules used by the analysis

Nothing is written in book.db: the suggestions only prefill the forms.
"""
