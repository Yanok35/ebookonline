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
Referential of the publishers: their names and aliases, and the ISBN
prefixes of some of them, read from publishers.json. See
docs/technote-metadata-publisher.md.
"""

import functools
import json
import os
import re
from collections import Counter, defaultdict

from srcs.metadata.text import clean_spaces, strip_accents

DEFAULT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "publishers.json")

# An alias with this prefix is searched case sensitive (a common word, e.g.
# "cs:Stock"); the other ones ignore the case and the accents.
CASE_SENSITIVE = "cs:"


class Publishers:

    def __init__(self, names, prefixes):
        """
        names: {canonical name: [aliases]}, prefixes: {ISBN-13 prefix
        (digits): canonical name}
        """
        self.names = {canon: list(aliases) for canon, aliases in names.items()}
        self.prefixes = dict(prefixes)
        # [(canonical name, regex, folded)]: a folded regex is searched in
        # the text in lower case and without accents
        self.patterns = []
        for canon, aliases in self.names.items():
            # the canonical name is also an alias, unless it is case
            # sensitive (e.g. "Stock": ["cs:Stock"])
            if CASE_SENSITIVE + canon not in aliases:
                aliases = aliases + [canon]
            for alias in sorted(set(aliases)):
                if alias.startswith(CASE_SENSITIVE):
                    regex = re.escape(alias[len(CASE_SENSITIVE):])
                    self.patterns.append((canon, re.compile(r"(?<![\w])" + regex + r"(?![\w])"), False))
                else:
                    regex = re.escape(strip_accents(alias).lower()).replace(r"\ ", r"\s+")
                    self.patterns.append((canon, re.compile(r"(?<![\w])" + regex + r"(?![\w])"), True))

    @classmethod
    def load(cls, path=DEFAULT_FILE):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(data.get("publishers", {}), data.get("isbn_prefixes", {}))

    def search(self, text):
        """
        [(canonical name, text around)]: the publishers named in a text, at
        most once each (first occurrence)
        """
        folded = strip_accents(text).lower()
        found = {}
        for canon, pat, is_folded in self.patterns:
            if canon in found:
                continue
            source = folded if is_folded else text
            m = pat.search(source)
            if m:
                found[canon] = source[max(0, m.start() - 80):m.start() + 80]
        return list(found.items())

    def canonical(self, name):
        """
        The canonical name of a publisher named in 'name' when known, or
        'name' cleaned up ('Les Éditions de la X' -> 'Éditions X', no
        'Inc.', 'Ltd', ... suffix)
        """
        if not name:
            return name
        folded = strip_accents(name).lower()
        for canon, pat, is_folded in self.patterns:
            if pat.search(folded if is_folded else name):
                return canon
        n = clean_spaces(name).strip(" .,;:-")
        if re.match(r"^(?:les\s+)?[ée]ditions?\s", n, re.IGNORECASE):
            n = re.sub(r"^(?:les\s+)?[ée]ditions?\s+(?:de\s+la\s+|de\s+l['’]|du\s+|des\s+|de\s+)?",
                       "Éditions ", n, flags=re.IGNORECASE)
        n = re.sub(r",?\s+(?:Inc|Ltd|LLC|S\.?A\.?S?|SARL|GmbH|Co)\.?$", "", n, flags=re.IGNORECASE)
        return n

    def is_known(self, name):
        return self.canonical(name) in self.names

    def by_prefix(self, isbn13):
        """ The publisher of an ISBN-13 from its prefix (longest first), or None """
        return prefix_lookup(self.prefixes, isbn13)


def prefix_lookup(prefixes, isbn13):
    for length in range(12, 5, -1):
        name = prefixes.get(isbn13[:length])
        if name:
            return name
    return None


def learn_prefixes(pairs, min_books=2, min_ratio=0.85):
    """
    {ISBN-13 prefix: publisher} learned from (ISBN-13, publisher) pairs: a
    prefix of 6 to 11 digits is kept when at least min_books books have it,
    and min_ratio of them the same publisher.
    """
    stats = defaultdict(Counter)
    for isbn13, name in pairs:
        for length in range(6, 12):
            stats[isbn13[:length]][name] += 1
    learned = {}
    for prefix, counter in stats.items():
        name, n = counter.most_common(1)[0]
        if n >= min_books and n / sum(counter.values()) >= min_ratio:
            learned[prefix] = name
    return learned


@functools.cache
def default():
    """ The referential of publishers.json, loaded once """
    return Publishers.load()
