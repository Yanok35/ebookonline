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

""" ISBN: validation, conversion to ISBN-13, search in a text """

import re
from collections import namedtuple


def isbn10_valid(d):
    if not re.fullmatch(r"\d{9}[\dX]", d):
        return False
    total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(d))
    return total % 11 == 0


def isbn13_check(d12):
    """ Check digit of the first 12 digits of an ISBN-13 """
    total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(d12))
    return str((10 - total % 10) % 10)


def isbn13_valid(d):
    return bool(re.fullmatch(r"97[89]\d{10}", d)) and isbn13_check(d[:12]) == d[12]


def to_isbn13(raw):
    """
    The ISBN-13 of an ISBN-10 or ISBN-13, with or without separators, or
    None when it is not valid (check digit).
    """
    d = re.sub(r"[^0-9Xx]", "", raw or "").upper()
    if len(d) == 13 and isbn13_valid(d):
        return d
    if len(d) == 10 and isbn10_valid(d):
        d12 = "978" + d[:9]
        return d12 + isbn13_check(d12)
    return None


# An ISBN found in a text: labelled when written after "ISBN" (otherwise a
# bare EAN-13 number), with the text around it
IsbnHit = namedtuple("IsbnHit", "isbn13 labelled context")

_SEP = r"[\s\-‐‑‒–—.]?"
RE_ISBN_LABEL = re.compile(
    r"(?:e[-\s]?)?ISBN(?:[-\s]?1[03])?(?:\s*\([^)]{0,30}\))?[^0-9Xx\n]{0,25}"
    r"((?:97[89]" + _SEP + r")?\d(?:" + _SEP + r"\d){8}" + _SEP + r"[\dXx])(?![\dXx])",
    re.IGNORECASE)
RE_EAN = re.compile(r"(?<![\d])(97[89](?:" + _SEP + r"\d){9}" + _SEP + r"\d)(?![\d])")

# Context of an ISBN: of the digital or of the printed edition
DIGITAL_CTX = re.compile(
    r"num[ée]rique|e-?book|epub|e-?isbn|digital|pdf|[ée]lectronique|kindle|mobi", re.IGNORECASE)
PRINT_CTX = re.compile(
    r"broch[ée]|papier|print|imprim[ée]|reli[ée]|paperback|hardcover|hardback|poche", re.IGNORECASE)


def find_isbns(text):
    """ [IsbnHit]: the valid ISBN of a text """
    found = []
    labelled_spans = []
    for m in RE_ISBN_LABEL.finditer(text):
        i13 = to_isbn13(m.group(1))
        if i13:
            found.append(IsbnHit(i13, True, text[max(0, m.start() - 60):m.end() + 40]))
            labelled_spans.append(m.span(1))
    for m in RE_EAN.finditer(text):
        if any(a <= m.start() < b for a, b in labelled_spans):
            continue
        i13 = to_isbn13(m.group(1))
        if i13:
            found.append(IsbnHit(i13, False, text[max(0, m.start() - 60):m.end() + 40]))
    return found
