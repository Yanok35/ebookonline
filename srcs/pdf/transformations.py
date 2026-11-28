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

from srcs.pdf import cover as pdfcover
from srcs.common.files import FileOperationError


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
        """ Write the transformed file dst from src, or raise FileOperationError """
        raise NotImplementedError

    def check(self, src, dst):
        """
        Raise FileOperationError when dst is not what it should be: the pages of
        the original, at page_offset, with the same text (the first and last
        pages compared)
        """
        try:
            old, new = pymupdf.open(src), pymupdf.open(dst)
        except Exception as e:
            raise FileOperationError(f"{self.name}: can not read the files: {e}") from None
        with old, new:
            if new.page_count != old.page_count + self.page_offset:
                raise FileOperationError(f"{self.name}: {new.page_count} pages instead of "
                                    f"{old.page_count + self.page_offset}")
            n = old.page_count
            for pno in sorted(set(range(min(CHECKED_PAGES, n)))
                              | set(range(max(0, n - CHECKED_PAGES), n))):
                a, b = old[pno], new[pno + self.page_offset]
                if (round(a.rect.width), round(a.rect.height)) != (round(b.rect.width), round(b.rect.height)):
                    raise FileOperationError(f"{self.name}: page {pno + 1} changed of size")
                if a.get_text() != b.get_text():
                    raise FileOperationError(f"{self.name}: the text of page {pno + 1} changed")


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


# Rendering compared: scale, pages (the first ones, the middle one, the
# last one), the tolerance (a byte of a pixel differing by more than
# PIXEL_TOLERANCE counts, more than RENDERING_TOLERANCE of them fail)
RENDERING_SCALE = 0.3
PIXEL_TOLERANCE = 16
RENDERING_TOLERANCE = 0.005
# An optimization is refused when the heaviest page keeps more than this
# part of its resources: nothing to gain
OPTIMIZATION_MIN_GAIN = 0.5


def same_rendering(a, b, pno_a, pno_b=None):
    """ Whether page pno_a of document a and page pno_b of b look the same, at low resolution """
    matrix = pymupdf.Matrix(RENDERING_SCALE, RENDERING_SCALE)
    pa = a[pno_a].get_pixmap(matrix=matrix, alpha=False)
    pb = b[pno_a if pno_b is None else pno_b].get_pixmap(matrix=matrix, alpha=False)
    if (pa.width, pa.height, pa.n) != (pb.width, pb.height, pb.n):
        return False
    differing = sum(1 for x, y in zip(pa.samples, pb.samples) if abs(x - y) > PIXEL_TOLERANCE)
    return differing <= RENDERING_TOLERANCE * len(pa.samples)


class ResourcesPerPage(Transformation):
    """
    Each page declares only the resources (images, fonts, ...) it uses:
    some books share one resource dictionary between all their pages, and
    the reader downloads all of it before drawing any page (see
    docs/technote-pdf-performance.md). Lossless: the same pages, the same
    rendering. The resources of the heaviest page, before and after, are
    in self.gain once checked.
    """

    name = "resources per page"

    def __init__(self):
        self.gain = None

    def apply(self, src, dst):
        try:
            doc = pymupdf.open(src)
        except Exception as e:
            raise FileOperationError(f"can not read the PDF file: {e}") from None
        with doc:
            if doc.needs_pass or doc.is_encrypted:
                raise FileOperationError(f"{self.name}: encrypted PDF file")
            try:
                for page in doc:
                    # the content streams rewritten, with the resources
                    # they use only
                    page.clean_contents(sanitize=True)
                doc.save(dst, garbage=3, deflate=True)
            except Exception as e:
                raise FileOperationError(f"{self.name}: {e}") from None

    def check(self, src, dst):
        from srcs.pdf import stats as pdfstats

        super().check(src, dst)
        with pymupdf.open(src) as old, pymupdf.open(dst) as new:
            # the text of every page, the rendering of a few ones
            for pno in range(old.page_count):
                if old[pno].get_text() != new[pno].get_text():
                    raise FileOperationError(f"{self.name}: the text of page {pno + 1} changed")
            n = old.page_count
            for pno in sorted({0, 1, 2, n // 2, n - 1} & set(range(n))):
                if not same_rendering(old, new, pno):
                    raise FileOperationError(f"{self.name}: the rendering of page {pno + 1} changed")
        before = pdfstats.measure(src)
        after = pdfstats.measure(dst)
        if before.get("error") or after.get("error"):
            raise FileOperationError(f"{self.name}: {before.get('error') or after.get('error')}")
        self.gain = (before["resources"]["max"], after["resources"]["max"])
        if not before["resources"]["max"] \
                or after["resources"]["max"] > OPTIMIZATION_MIN_GAIN * before["resources"]["max"]:
            raise FileOperationError(f"{self.name}: nothing to gain, the heaviest page keeps "
                                f"{after['resources']['max'] / 1048576:.1f} MB of resources")
