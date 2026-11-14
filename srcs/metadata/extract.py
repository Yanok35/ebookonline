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
Raw data of a PDF file, read once and kept in the cache, from which the
candidate values of the metadata are found (srcs/metadata/analyse.py):

- the metadata of the document (Info dictionary) and its XMP fields;
- the text of the first and last pages (title page, copyright page,
  colophon);
- the lines of the first pages, with the size of their font (the title is
  usually the largest text of the title page).

Only these pages are read, not the whole file.
"""

import html
import re

import pymupdf

from srcs.metadata.isbn import find_isbns
from srcs.metadata.text import clean_spaces

# Version of the raw data: incremented when other data is read from the PDF
# files (e.g. more pages). The cache files of an older version are extracted
# again, which opens all the PDF files: see analyse.ANALYSER_VERSION for a
# change of the rules only.
EXTRACT_VERSION = 1

FIRST_PAGES = 15
LAST_PAGES = 6
# Pages whose lines are read with their font size
FONT_PAGES = 4
# A document with less text in its key pages has no usable text layer (a
# scan without OCR)
MIN_TEXT_CHARS = 200

XMP_TAGS = ("dc:creator", "dc:publisher", "dc:title", "dc:date", "dc:language",
            "dc:identifier", "xmp:Identifier", "prism:isbn", "pdf:Keywords")

# Errors of MuPDF on a malformed PDF file: PyMuPDF raises RuntimeError (or a
# subclass), its low level layer FzErrorBase subclasses (FzErrorFormat:
# "object is not a stream", ...), which are not RuntimeError
MUPDF_ERRORS = (RuntimeError, pymupdf.mupdf.FzErrorBase)

# MuPDF messages (e.g. on a malformed PDF file) are not printed
pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)


class ExtractError(Exception):
    """ The PDF file can not be read """


def key_pages(count, first=FIRST_PAGES, last=LAST_PAGES):
    """ Indexes of the first and last pages of a document of count pages """
    return sorted(set(range(min(first, count))) | set(range(max(0, count - last), count)))


def xmp_fields(xmp):
    """
    {tag: [values]} of the XMP metadata (see XMP_TAGS), 'isbns': the ISBN
    found anywhere in it, 'calibre': true when written by calibre
    """
    out = {}
    if not xmp:
        return out
    for tag in XMP_TAGS:
        values = []
        for m in re.finditer(rf"<{tag}\b[^>]*>(.*?)</{tag}>", xmp, re.DOTALL):
            inner = m.group(1)
            for item in re.findall(r"<rdf:li\b[^>]*>(.*?)</rdf:li>", inner, re.DOTALL) or [inner]:
                item = clean_spaces(html.unescape(re.sub(r"<[^>]+>", " ", item)))
                if item:
                    values.append(item)
        for m in re.finditer(rf'\b{tag}="([^"]+)"', xmp):
            values.append(clean_spaces(html.unescape(m.group(1))))
        if values:
            out[tag] = values
    plain = clean_spaces(html.unescape(re.sub(r"<[^>]+>", " ", xmp)))
    isbns = sorted({hit.isbn13 for hit in find_isbns(plain)})
    if isbns:
        out["isbns"] = isbns
    if "calibre" in xmp.lower():
        out["calibre"] = True
    return out


def _font_lines(page):
    """ [[font size, text]] of the lines of a page """
    lines = []
    # text only: the images of the page (their bytes) are not loaded
    for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT).get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = clean_spaces("".join(s.get("text", "") for s in spans))
            if text and spans:
                lines.append([round(max(s.get("size", 0) for s in spans), 1), text])
    return lines


def extract(path):
    """
    The raw data of a PDF file, a dict which can be saved as JSON:

    - pages: number of pages
    - meta: {key: value} of the Info dictionary (keys in lower case)
    - xmp: see xmp_fields()
    - texts: {page index (str): text} of the key pages
    - fonts: [[page index, [[font size, line]]]] of the first pages
    - has_text: false when the key pages have (almost) no text

    Raises ExtractError when the file can not be read. A damaged part
    (metadata, XMP, a page) is skipped: the other ones are still used.
    """
    try:
        doc = pymupdf.open(path, filetype="pdf")
    except (*MUPDF_ERRORS, OSError) as e:
        raise ExtractError(f"can not open the PDF file: {e}") from None
    try:
        if doc.needs_pass and not doc.authenticate(""):
            raise ExtractError("encrypted PDF file, with a password")
        count = doc.page_count
        try:
            meta = {k.lower(): clean_spaces(str(v))
                    for k, v in (doc.metadata or {}).items() if v}
        except MUPDF_ERRORS:
            meta = {}
        try:
            xmp = doc.get_xml_metadata() or ""
        except MUPDF_ERRORS:
            # e.g. "object is not a stream": a damaged XMP metadata
            xmp = ""
        texts = {}
        for i in key_pages(count):
            try:
                texts[str(i)] = doc[i].get_text("text")
            except MUPDF_ERRORS:
                texts[str(i)] = ""
        fonts = []
        for i in range(min(FONT_PAGES, count)):
            try:
                fonts.append([i, _font_lines(doc[i])])
            except MUPDF_ERRORS:
                pass
    except MUPDF_ERRORS as e:
        raise ExtractError(f"can not read the PDF file: {e}") from None
    finally:
        doc.close()

    return {
        "pages": count,
        "meta": meta,
        "xmp": xmp_fields(xmp),
        "texts": texts,
        "fonts": fonts,
        "has_text": sum(len(t.strip()) for t in texts.values()) >= MIN_TEXT_CHARS,
    }
