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
Cache file of the metadata of a book: CACHE_DIR/<sha1>.meta.json.gz, a
JSON object compressed with gzip. It only depends on the content of the PDF
file (thus on its sha1), never on the user values of book.db: it can be
removed, it is made again.

- sha1: of the PDF file
- extract_version, analyser_version: versions of the code which wrote raw
  and candidates (see extract.EXTRACT_VERSION, analyse.ANALYSER_VERSION)
- extracted_at, analysed_at: dates (ISO 8601, UTC)
- error: why the PDF file could not be read, or null; then raw and
  candidates are empty
- raw: the raw data of the PDF file (extract.extract())
- candidates: {field: [[value, source, weight]]} (analyse.candidates())
"""

import datetime
import gzip
import json
import logging
import os

from srcs.common.files import atomic_write
from srcs.metadata import analyse, extract

log = logging.getLogger(__name__)

SUFFIX = ".meta.json.gz"


def path(cache_dir, sha1):
    return os.path.join(cache_dir, sha1 + SUFFIX)


def read(cache_dir, sha1):
    """ The content of the cache file of a book, or None (missing, unreadable) """
    try:
        with gzip.open(path(cache_dir, sha1), "rt", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, EOFError, ValueError) as e:
        log.warning("Unreadable metadata cache file of %s: %s", sha1, e)
        return None


def write(cache_dir, entry):
    """ Write a cache file: to a temporary file, then renamed """
    def gzipped(f):
        with gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as gz:
            gz.write(json.dumps(entry, ensure_ascii=False).encode("utf-8"))

    atomic_write(path(cache_dir, entry["sha1"]), gzipped, binary=True, prefix=".meta-")


def _now():
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


# Prefix of the error of an unexpected exception of the analysis (see
# service._worker_main()): a bug, not a damaged PDF file
INTERNAL_ERROR = "analysis failed: "


def is_internal_error(entry):
    return entry is not None and (entry.get("error") or "").startswith(INTERNAL_ERROR)


def is_extracted(entry):
    """
    True when the raw data (or the error) of entry is up to date. An
    internal error is not: the book is tried again, once per start of the
    server, in case the bug was fixed.
    """
    return entry is not None and entry.get("extract_version") == extract.EXTRACT_VERSION \
        and not is_internal_error(entry)


def is_current(entry):
    """ True when nothing has to be done for entry """
    return is_extracted(entry) and (
        entry.get("error") is not None
        or entry.get("analyser_version") == analyse.ANALYSER_VERSION)


# Results of update()
CURRENT = "current"      # nothing to do
ANALYSED = "analysed"    # candidates found again from the raw data
EXTRACTED = "extracted"  # PDF file read, and analysed
FAILED = "failed"        # PDF file which can not be read (error saved)
MISSING = "missing"      # no PDF file at this path (nothing saved)


def update(cache_dir, sha1, pdf_path, force=False):
    """
    Make the cache file of a book up to date, from its PDF file pdf_path,
    only when needed. force: read the PDF file again. Returns one of
    CURRENT, ANALYSED, EXTRACTED, FAILED, MISSING.
    """
    entry = None if force else read(cache_dir, sha1)
    if is_current(entry):
        return CURRENT

    if is_extracted(entry):
        status = ANALYSED
    else:
        if not os.path.isfile(pdf_path):
            return MISSING
        entry = {"sha1": sha1, "extract_version": extract.EXTRACT_VERSION,
                 "extracted_at": _now(), "error": None}
        try:
            entry["raw"] = extract.extract(pdf_path)
            status = EXTRACTED
        except extract.ExtractError as e:
            entry.update(error=str(e), raw={}, candidates={},
                         analyser_version=None, analysed_at=None)
            write(cache_dir, entry)
            return FAILED

    entry["candidates"] = analyse.candidates(entry["raw"])
    entry["analyser_version"] = analyse.ANALYSER_VERSION
    entry["analysed_at"] = _now()
    write(cache_dir, entry)
    return status


def write_error(cache_dir, sha1, error):
    """ Save that the PDF file of a book can not be read (e.g. crash of MuPDF) """
    write(cache_dir, {"sha1": sha1, "extract_version": extract.EXTRACT_VERSION,
                      "extracted_at": _now(), "error": error, "raw": {},
                      "candidates": {}, "analyser_version": None, "analysed_at": None})
