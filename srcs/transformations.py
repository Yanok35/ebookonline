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
Transformations of the PDF file of a book, made in place by
BookDir.transform(): the transformed file replaces the original, which
goes to the trash ('name (original).pdf'). See
docs/technote-pdf-performance.md.

A transformation writes the new file (apply()), checks it against the
original (check()), and tells what it keeps of the original: the first
page (then the thumbnail is kept), the text (then the metadata analysis
is kept), and how the pages move (page_offset: the reading positions
follow).
"""

import pymupdf

from srcs import pdfcover
from srcs.bookfileops import BookFileError

# MuPDF messages (e.g. on a malformed PDF file) are not printed
pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)

# Pages whose text is compared, at the beginning and at the end
CHECKED_PAGES = 3


class Transformation:
    """ A transformation of the PDF file of a book """

    # for the logs
    name = "transformation"
    # what the new file keeps of the original
    keeps_first_page = True
    keeps_text = True
    # page n of the original is page n + page_offset of the new file
    page_offset = 0

    def apply(self, src, dst):
        """ Write the transformed file dst from src, or raise BookFileError """
        raise NotImplementedError

    def check(self, src, dst):
        """
        Raise BookFileError when dst is not what it should be: the pages of
        the original, at page_offset, with the same text (the first and last
        pages compared)
        """
        try:
            old, new = pymupdf.open(src), pymupdf.open(dst)
        except Exception as e:
            raise BookFileError(f"{self.name}: can not read the files: {e}") from None
        with old, new:
            if new.page_count != old.page_count + self.page_offset:
                raise BookFileError(f"{self.name}: {new.page_count} pages instead of "
                                    f"{old.page_count + self.page_offset}")
            n = old.page_count
            for pno in sorted(set(range(min(CHECKED_PAGES, n)))
                              | set(range(max(0, n - CHECKED_PAGES), n))):
                a, b = old[pno], new[pno + self.page_offset]
                if (round(a.rect.width), round(a.rect.height)) != (round(b.rect.width), round(b.rect.height)):
                    raise BookFileError(f"{self.name}: page {pno + 1} changed of size")
                if a.get_text() != b.get_text():
                    raise BookFileError(f"{self.name}: the text of page {pno + 1} changed")


class CoverPage(Transformation):
    """ A first page showing an image (bytes of a JPEG or PNG file) """

    name = "cover page"
    keeps_first_page = False
    keeps_text = False
    page_offset = 1

    def __init__(self, image):
        self.image = image

    def apply(self, src, dst):
        pdfcover.insert_cover(src, self.image, dst)
