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
Typo tolerant search of books by their file name.

The query and the file names are normalized (case, accents, punctuation)
and split into words. Each query word must match a word of the file name
(all query words are required, in any order), either:

- exactly, or as the beginning of a word (the search runs while typing),
  or inside a word (3 characters at least, e.g. 'thon' in 'python');
- with a few typos (insertion, deletion, substitution or swap of two
  adjacent characters), against the whole word or its beginning. The
  number of typos allowed grows with the length of the query word: none
  up to 2 characters, 1 up to 5, 2 beyond.

Results are sorted by relevance: the query found as is in the name first,
then exact word matches, then matches with the fewest typos.
"""

import functools
import os
import re
import unicodedata

from rapidfuzz import process
from rapidfuzz.distance import OSA

# Costs of a query word match (lower is better)
EXACT = 0.0
PREFIX = 0.1
INSIDE = 0.3
TRUNCATED = 0.1     # added to typos counted against the beginning of a word
PHRASE_BONUS = -1.0  # the whole normalized query is found in the name

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def normalize(text):
    """ 'Élève_C++ (2nd-ed).pdf' -> 'eleve c 2nd ed pdf' """
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    # "o'reilly" -> "oreilly", as typed by most users
    text = text.replace("'", "").replace("’", "")
    return _NON_ALNUM.sub(" ", text).strip()


@functools.lru_cache(maxsize=65536)
def name_words(filename):
    """ Normalized words of a book file name, without its extension """
    name = os.path.basename(filename)
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    normalized = normalize(name)
    return normalized, tuple(normalized.split())


def max_typos(word):
    if len(word) <= 2:
        return 0
    if len(word) <= 5:
        return 1
    return 2


def _word_costs(qword, vocabulary):
    """ {word of the vocabulary: cost} for the words matching qword """
    costs = {}

    def keep(word, cost):
        if cost < costs.get(word, float("inf")):
            costs[word] = cost

    for word in vocabulary:
        if word == qword:
            keep(word, EXACT)
        elif word.startswith(qword):
            keep(word, PREFIX)
        elif len(qword) >= 3 and qword in word:
            keep(word, INSIDE)

    typos = max_typos(qword)
    if typos:
        # whole words: 'pyhton' -> 'python'
        for word, distance, _ in process.extract(
                qword, vocabulary, scorer=OSA.distance,
                score_cutoff=typos, limit=None):
            keep(word, distance)
        # beginning of words, while typing: 'pyht' -> 'python'
        n = len(qword)
        longer = [w for w in vocabulary if len(w) > n]
        heads = [w[:n] for w in longer]
        for _, distance, i in process.extract(
                qword, heads, scorer=OSA.distance,
                score_cutoff=typos, limit=None):
            keep(longer[i], distance + TRUNCATED)

    return costs


def fuzzy_search(books, query):
    """
    Books of 'books' whose file name matches 'query', most relevant first.
    An empty query matches every book, in the original order.
    """
    query_norm = normalize(query)
    qwords = query_norm.split()
    if not qwords:
        return list(books)

    vocabulary = list({w for b in books for w in name_words(b.filename)[1]})
    costs = [_word_costs(q, vocabulary) for q in qwords]

    scored = []
    for rank, book in enumerate(books):
        normalized, words = name_words(book.filename)
        total = 0.0
        for qcosts in costs:
            best = min((qcosts[w] for w in words if w in qcosts), default=None)
            if best is None:
                break
            total += best
        else:
            if query_norm in normalized:
                total += PHRASE_BONUS
            scored.append((total, rank, book))

    scored.sort(key=lambda s: (s[0], s[1]))
    return [book for _, _, book in scored]
