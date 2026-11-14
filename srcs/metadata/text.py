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

""" Text helpers of the metadata analysis """

import re
import unicodedata


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def norm_key(s):
    """ Comparison key: lower case, without accents, alphanumeric only """
    s = strip_accents(s or "").lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def clean_spaces(s):
    """ Single spaces (non-breaking ones included), stripped """
    return re.sub(r"\s+", " ", (s or "").replace(" ", " ")).strip()


def fix_case(s):
    """ 'VICTOR HUGO' -> 'Victor Hugo'; a mixed case is left unchanged """
    if s.isupper() and len(s) > 3:
        out = s.title()
        out = re.sub(r"\b(De|Du|Des|D'|Von|Van|Der|Den|Le|La|Di|Da|Del)\b",
                     lambda m: m.group(1).lower(), out)
        return out[0].upper() + out[1:]
    return s
