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
Insert a cover page, made of an image, in front of a PDF file (PyMuPDF).

The other pages, the outline (table of contents), the links and the
metadata of the document are kept: the outline and the links point to page
objects, which are not changed by the insertion. The page labels (the page
numbers shown by readers) are shifted, so that each page keeps its label.
"""

import logging
import struct

import pymupdf

from srcs.bookfileops import BookFileError

log = logging.getLogger(__name__)

# MuPDF messages (e.g. on a malformed PDF file) are logged, not printed
pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)

# Limits of the image: size of the file, and number of pixels once decoded
# (checked before decoding it: about 90 MB in memory at most)
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 30_000_000

# Page label of the inserted cover
COVER_LABEL = "Cover"

# JPEG start of frame markers, which give the size of the image
_JPEG_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
             0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def image_info(data):
    """
    ('jpeg' or 'png', width, height) of an image, read from its header (the
    image is not decoded), or raise BookFileError: unsupported format,
    truncated header, size over the limits.
    """
    if len(data) > MAX_IMAGE_BYTES:
        raise BookFileError(f"image too large: {len(data)} bytes, "
                            f"{MAX_IMAGE_BYTES} at most")
    if data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        kind = "png"
        width, height = struct.unpack(">II", data[16:24])
    elif data.startswith(b"\xff\xd8"):
        kind = "jpeg"
        width = height = None
        i = 2
        while i + 9 <= len(data):
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            if marker == 0xFF:          # fill byte
                i += 1
                continue
            if marker in (0x01, *range(0xD0, 0xD8)):   # without length
                i += 2
                continue
            length = struct.unpack(">H", data[i + 2:i + 4])[0]
            if marker in _JPEG_SOF:
                height, width = struct.unpack(">HH", data[i + 5:i + 9])
                break
            i += 2 + length
        if not width or not height:
            raise BookFileError("invalid JPEG image")
    else:
        raise BookFileError("not a JPEG or PNG image")
    if not width or not height:
        raise BookFileError(f"invalid {kind.upper()} image size")
    if width * height > MAX_IMAGE_PIXELS:
        raise BookFileError(f"image too large: {width}x{height} pixels")
    return kind, width, height


def check_image(data):
    """
    ('jpeg' or 'png', width, height) of a valid image, or raise
    BookFileError. The image is decoded, once its header checked: MuPDF
    shows a damaged (e.g. truncated) image as it can, an error or a warning
    while decoding it refuses it.
    """
    kind, width, height = image_info(data)
    pymupdf.TOOLS.reset_mupdf_warnings()
    try:
        pymupdf.Pixmap(data)
    except Exception as e:
        raise BookFileError(f"invalid {kind.upper()} image: {e}") from None
    warnings = pymupdf.TOOLS.mupdf_warnings()
    if warnings:
        raise BookFileError(f"damaged {kind.upper()} image: {warnings.splitlines()[0]}")
    return kind, width, height


def _shifted_labels(labels):
    """
    The page labels once the cover inserted in front: a label of its own for
    the cover, the other ranges start one page later. A document without
    labels gets its current numbering as labels (1, 2, ...), which then
    still matches the printed page numbers.
    """
    if not labels:
        labels = [{"startpage": 0, "prefix": "", "style": "D", "firstpagenum": 1}]
    shifted = [{"startpage": 0, "prefix": COVER_LABEL, "firstpagenum": 1}]
    for label in labels:
        shifted.append(dict(label, startpage=label["startpage"] + 1))
    return shifted


def insert_cover(pdf_path, image, out_path):
    """
    Write in out_path the PDF file pdf_path, with a first page showing the
    image (bytes of a JPEG or PNG file). The page has the width of the first
    page of the document, and the ratio of the image. Raise BookFileError on
    an invalid image or PDF file.
    """
    kind, width, height = check_image(image)
    pymupdf.TOOLS.reset_mupdf_warnings()
    try:
        doc = pymupdf.open(pdf_path, filetype="pdf")
    except (pymupdf.FileDataError, RuntimeError) as e:
        raise BookFileError(f"can not read the PDF file: {e}") from None
    try:
        if doc.needs_pass:
            raise BookFileError("the PDF file is protected by a password")
        if doc.page_count == 0:
            raise BookFileError("the PDF file has no page")

        labels = _shifted_labels(doc.get_page_labels())
        page_width = doc[0].rect.width
        page = doc.new_page(pno=0, width=page_width,
                            height=page_width * height / width)
        try:
            page.insert_image(page.rect, stream=image)
        except (ValueError, RuntimeError) as e:
            raise BookFileError(f"invalid {kind.upper()} image: {e}") from None
        doc.set_page_labels(labels)
        doc.save(out_path, encryption=pymupdf.PDF_ENCRYPT_KEEP)
    finally:
        doc.close()
        warnings = pymupdf.TOOLS.mupdf_warnings()
        if warnings:
            log.debug("MuPDF messages for %s:\n%s", pdf_path, warnings)
