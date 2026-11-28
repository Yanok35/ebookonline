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
Indicators of the structure of a PDF file, to understand why a book is
slow to open in the reader (see docs/technote-pdf-performance.md):
weight by kind of object, images, fonts, content streams, and above all
the resources each page declares, which pdf.js downloads before drawing
the page.

measure() reads the file without rendering it (a few hundred ms for a
large book). The result is kept in CACHE_DIR/<sha1>.pdfstats.json (it
only depends on the content of the file); warnings() tells the problems
found, from it.
"""

import collections
import datetime
import json
import logging
import os
import statistics

import pymupdf

from srcs.common.files import atomic_write

# The errors of damaged files: not printed (the indicators tell them)
pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)

log = logging.getLogger(__name__)

# Version of the indicators: a cache file of another version is measured
# again
STATS_VERSION = 1
SUFFIX = ".pdfstats.json"

MB = 1024 * 1024

# Warnings: thresholds
SHARED_RESOURCES_BYTES = 10 * MB    # resources declared by a page
SHARED_RESOURCES_IMAGES = 20        # images declared by a page
LARGE_IMAGE_PIXELS = 20_000_000     # one image
COMPLEX_PAGE_BYTES = 1 * MB         # content stream of a page

FONT_FILE_KEYS = ("FontFile", "FontFile2", "FontFile3")


def _key(doc, xref, key):
    """ The value of key in the object xref, None if missing or unreadable """
    try:
        kind, value = doc.xref_get_key(xref, key)
    except Exception:
        # a damaged object: MuPDF may still use it (repaired)
        return None
    return None if kind == "null" else value


def _ref(value):
    """ The xref of a reference "12 0 R", or None """
    if value and value.endswith(" R"):
        try:
            return int(value.split()[0])
        except ValueError:
            return None
    return None


def measure(pdf_path):
    """
    The indicators of a PDF file, a dict which can be saved as JSON; or
    {"error": ...} when the file can not be read.
    """
    try:
        doc = pymupdf.open(pdf_path, filetype="pdf")
    except Exception as e:
        return {"error": f"can not open the PDF file: {e}"}
    try:
        return _measure(doc, pdf_path)
    except Exception as e:
        log.warning("PDF indicators of %s: %s", pdf_path, e)
        return {"error": f"can not read the PDF file: {e}"}
    finally:
        doc.close()


def _colorspace(doc, value):
    """
    The name of a colour space: DeviceRGB, DeviceGray, DeviceCMYK, ICC
    (ICCBased), Indexed, ... (a reference is resolved)
    """
    if not value:
        return "none"
    ref = _ref(value)
    if ref is not None:
        try:
            value = doc.xref_object(ref, compressed=True)
        except Exception:
            return "other"
    value = value.strip().lstrip("[").strip()
    if not value.startswith("/"):
        return "other"
    name = value[1:].split("/")[0].split()[0].split("[")[0]
    return "ICC" if name == "ICCBased" else name


def _measure(doc, pdf_path):
    size = os.path.getsize(pdf_path)
    stats = {
        "file": {
            "size": size,
            "pages": doc.page_count,
            "version": doc.metadata.get("format") or "",
            "producer": doc.metadata.get("producer") or "",
            "creator": doc.metadata.get("creator") or "",
            "linearized": bool(doc.is_fast_webaccess),
            "encrypted": bool(doc.is_encrypted),
            "objects": doc.xref_length() - 1,
            # versions of the file: one more per incremental update
            "updates": max(0, doc.version_count - 1),
        },
        "outline": len(doc.get_toc(simple=True)),
    }

    # --- every object: the size of the streams by kind, images, fonts
    length = {}            # xref -> size of its stream in the file
    by_kind = collections.Counter()
    images = []
    font_program = {}      # xref of a font program -> its size
    descriptors = []       # xref of the font descriptors
    fonts = []             # xref of the fonts
    for xref in range(1, doc.xref_length()):
        try:
            typ = _key(doc, xref, "Type")
            if doc.xref_is_stream(xref):
                n = len(doc.xref_stream_raw(xref) or b"")
                length[xref] = n
                subtype = _key(doc, xref, "Subtype")
                if subtype == "/Image":
                    by_kind["images"] += n
                    images.append(xref)
                elif typ in ("/ObjStm", "/XRef", "/Metadata"):
                    by_kind["other"] += n
                elif subtype == "/Form":
                    by_kind["content"] += n
                else:
                    # content streams, font programs (sorted out below), ...
                    by_kind["streams"] += n
            elif typ == "/FontDescriptor":
                descriptors.append(xref)
            elif typ == "/Font":
                fonts.append(xref)
        except Exception:
            continue

    for xref in descriptors:
        for key in FONT_FILE_KEYS:
            program = _ref(_key(doc, xref, key))
            if program and program in length:
                font_program[xref] = length[program]
                by_kind["fonts"] += length[program]
                by_kind["streams"] -= length[program]
    by_kind["content"] += by_kind.pop("streams", 0)

    # the size of the program of a font (Type0: of its descendant)
    font_bytes = {}
    subtypes = collections.Counter()
    subsets = embedded = 0
    for xref in fonts:
        subtype = _key(doc, xref, "Subtype") or ""
        subtypes[subtype.lstrip("/")] += 1
        base = (_key(doc, xref, "BaseFont") or "").lstrip("/")
        if len(base) > 7 and base[6] == "+":
            subsets += 1
        descriptor = _ref(_key(doc, xref, "FontDescriptor"))
        if descriptor is None and subtype == "/Type0":
            descendants = _key(doc, xref, "DescendantFonts") or ""
            child = _ref(descendants.strip("[] "))
            if child:
                descriptor = _ref(_key(doc, child, "FontDescriptor"))
        if descriptor in font_program:
            embedded += 1
            font_bytes[xref] = font_program[descriptor]
    stats["fonts"] = {"count": len(fonts), "embedded": embedded, "subsets": subsets,
                      "type3": subtypes.get("Type3", 0), "kinds": dict(subtypes)}

    # --- images
    pixels = []
    filters = collections.Counter()
    colorspaces = collections.Counter()
    soft_masks = 0
    largest = None
    for xref in images:
        width = int(_key(doc, xref, "Width") or 0)
        height = int(_key(doc, xref, "Height") or 0)
        filt = (_key(doc, xref, "Filter") or "none").strip("[]/ ").replace(" /", ", ")
        cs = _colorspace(doc, _key(doc, xref, "ColorSpace"))
        filters[filt] += 1
        colorspaces[cs] += 1
        if _key(doc, xref, "SMask"):
            soft_masks += 1
        pixels.append(width * height)
        if largest is None or length[xref] > largest["bytes"]:
            largest = {"bytes": length[xref], "width": width, "height": height,
                       "filter": filt, "colorspace": cs}
    stats["images"] = {
        "count": len(images),
        "bytes": by_kind["images"],
        "max_pixels": max(pixels, default=0),
        "largest": largest,
        "filters": dict(filters),
        "colorspaces": dict(colorspaces),
        "cmyk": colorspaces.get("DeviceCMYK", 0),
        "jpx": filters.get("JPXDecode", 0),
        "soft_masks": soft_masks,
    }
    stats["bytes"] = {k: by_kind.get(k, 0) for k in ("images", "fonts", "content", "other")}

    # --- pages: content streams, resources declared (what pdf.js loads
    # before drawing the page)
    contents = []
    resources = []         # (bytes, page number, images declared)
    annotations = 0
    # (bytes, images) of a resource dictionary shared by pages: measured
    # once (a book may share one dictionary of hundreds of images)
    shared = {}
    for page in doc:
        try:
            page_resources = _page_resources(doc, page, length, font_bytes, shared)
        except Exception as e:
            # a damaged page: left out of the indicators of the pages
            log.debug("PDF indicators of %s, page %d: %s", pdf_path, page.number + 1, e)
            continue
        contents.append(page_resources[0])
        resources.append(page_resources[1])
        annotations += page_resources[2]

    stats["annotations"] = annotations
    if contents:
        largest_page = max(range(len(contents)), key=contents.__getitem__)
        stats["content"] = {"median": int(statistics.median(contents)),
                            "max": contents[largest_page], "max_page": largest_page + 1}
        # (the first one of the heaviest pages)
        heaviest = max(resources, key=lambda r: (r[0], -r[1]))
        stats["resources"] = {
            "median": int(statistics.median(r[0] for r in resources)),
            "max": heaviest[0], "max_page": heaviest[1],
            "max_images": max(r[2] for r in resources),
            "pages_over": sum(1 for r in resources if r[0] > SHARED_RESOURCES_BYTES),
        }
    else:
        stats["content"] = {"median": 0, "max": 0, "max_page": None}
        stats["resources"] = {"median": 0, "max": 0, "max_page": None,
                              "max_images": 0, "pages_over": 0}
    return stats


def _page_resources(doc, page, length, font_bytes, shared):
    """
    (size of its content streams, (bytes of the resources it declares, page
    number, images declared), annotations) of a page. shared: the (bytes,
    images) of the resource dictionaries already measured (a book may share
    one dictionary of hundreds of images between its pages)
    """
    content = sum(length.get(x, 0) for x in page.get_contents())
    # the same resources: the same dictionary, referenced ("12 0 R") or
    # written again in each page (its text: some books repeat a dictionary
    # of hundreds of patterns in every page); None: inherited from the
    # page tree, measured for each page
    key = _key(doc, page.xref, "Resources")
    if key is not None and key in shared:
        page_bytes, n_images = shared[key]
    else:
        declared = set()
        n_images = 0
        for img in page.get_images(full=True):
            declared.add(img[0])
            n_images += 1
            if img[1]:
                declared.add(img[1])     # its soft mask
        for xobj in page.get_xobjects():
            declared.add(xobj[0])
        page_bytes = sum(length.get(x, 0) for x in declared)
        page_bytes += sum(font_bytes.get(f[0], 0) for f in page.get_fonts(full=True))
        if key is not None:
            shared[key] = (page_bytes, n_images)
    return content, (page_bytes, page.number + 1, n_images), len(page.annot_xrefs())


def optimizable(stats):
    """
    Whether the resources per page (srcs/transformations.py) may lighten
    the book: a page declares too many resources
    """
    return bool(stats) and not stats.get("error") \
        and stats["resources"]["max"] > SHARED_RESOURCES_BYTES


def _mb(n):
    return f"{n / MB:.1f} Mo"


def warnings(stats):
    """ [message]: the problems found in the indicators, in French (book page) """
    if not stats or stats.get("error"):
        return []
    out = []
    res = stats["resources"]
    if res["max"] > SHARED_RESOURCES_BYTES and res["max_images"] > SHARED_RESOURCES_IMAGES:
        out.append(f"Ressources partagées : la page {res['max_page']} déclare {res['max_images']} images, "
                   f"{_mb(res['max'])} chargés avant son affichage ({res['pages_over']} pages au-delà de "
                   f"{_mb(SHARED_RESOURCES_BYTES)}).")
    elif res["max"] > SHARED_RESOURCES_BYTES:
        out.append(f"Page lourde : la page {res['max_page']} charge {_mb(res['max'])} avant son affichage.")
    img = stats["images"]
    if img["cmyk"]:
        out.append(f"{img['cmyk']} image(s) CMJN : conversion lente dans le navigateur.")
    if img["jpx"]:
        out.append(f"{img['jpx']} image(s) JPEG 2000 : décodage lent dans le navigateur.")
    if img["max_pixels"] > LARGE_IMAGE_PIXELS:
        out.append(f"Image très grande : {img['max_pixels'] / 1e6:.0f} mégapixels.")
    if stats["fonts"]["type3"]:
        out.append(f"{stats['fonts']['type3']} police(s) Type 3 : dessinées comme des tracés, lentes.")
    if stats["content"]["max"] > COMPLEX_PAGE_BYTES:
        out.append(f"Page complexe : le contenu de la page {stats['content']['max_page']} "
                   f"fait {_mb(stats['content']['max'])}.")
    return out


# --- cache file

def path(cache_dir, sha1):
    return os.path.join(cache_dir, sha1 + SUFFIX)


def read(cache_dir, sha1):
    """ The cached indicators of a book (current version), or None """
    try:
        with open(path(cache_dir, sha1), encoding="utf-8") as f:
            entry = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log.warning("Unreadable PDF indicators of %s: %s", sha1, e)
        return None
    return entry if entry.get("version") == STATS_VERSION else None


def get(cache_dir, sha1, pdf_path, writable=True, force=False):
    """
    The indicators of a book: the cached ones, or measured (and cached when
    writable). None when the file is missing.
    """
    entry = None if force else read(cache_dir, sha1)
    if entry is not None:
        return entry
    if not os.path.isfile(pdf_path):
        return None
    entry = measure(pdf_path)
    entry.update(version=STATS_VERSION, sha1=sha1,
                 measured_at=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"))
    if writable:
        _write(cache_dir, entry)
    return entry


def _write(cache_dir, entry):
    atomic_write(path(cache_dir, entry["sha1"]), lambda f: json.dump(entry, f), prefix=".pdfstats-")
