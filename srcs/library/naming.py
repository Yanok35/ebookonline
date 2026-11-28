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
Names of the PDF files from the metadata of the books (book.db), after a
pattern (FILENAME_PATTERN), e.g. "{title} {subtitle} - {author_sort}, {year}"
-> "Python Algorithms Mastering Basic Algorithms in the Python Language -
Hetland, Magnus Lie, 2014.pdf". See docs/technote-file-naming.md.
"""

import os
import re
import string
import unicodedata

from srcs.metadata.names import PARTICLES

# Variables of a pattern, from the attributes of srcs.library.book.Book
VARIABLES = {
    "title": "titre",
    "subtitle": "sous-titre",
    "author": "premier auteur",
    "authors": "auteurs (« et al. » au-delà de 2)",
    "author_sort": "premier auteur, nom d'abord (Hugo, Victor)",
    "editor": "éditeur",
    "year": "année",
    "isbn": "ISBN",
}

# Largest name of a file, in bytes (UTF-8): 255 on most file systems, a
# little less to stay away from the limit
MAX_NAME_BYTES = 240

SUFFIX = ".pdf"

# Particles which stay with the given name in the sort form (French usage:
# "Saint-Exupéry, Antoine de"); the other ones go with the surname
# ("van Beethoven, Ludwig")
_GIVEN_NAME_PARTICLES = {"de", "d'", "d’", "von"}
_NAME_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}


class NamingError(ValueError):
    """ No name can be made for a book (e.g. no title), or invalid pattern """


def check_pattern(pattern):
    """
    The variables of a pattern; raises NamingError for an invalid pattern
    (directory, unknown variable, format specification)
    """
    if not pattern or "/" in pattern or "\\" in pattern:
        raise NamingError(f"invalid file name pattern: {pattern!r} (no directory)")
    try:
        fields = [(name, spec, conv) for _, name, spec, conv in string.Formatter().parse(pattern)
                  if name is not None]
    except ValueError as e:
        raise NamingError(f"invalid file name pattern: {pattern!r}: {e}") from None
    if any(spec or conv for _, spec, conv in fields):
        raise NamingError(f"invalid file name pattern: {pattern!r} (no format specification)")
    names = [name for name, _, _ in fields]
    unknown = [n for n in names if n not in VARIABLES]
    if unknown:
        raise NamingError(f"unknown variables in the file name pattern {pattern!r}: "
                          + ", ".join(unknown))
    if not names:
        raise NamingError(f"file name pattern without variable: {pattern!r}")
    return names


def author_sort(name):
    """ 'Antoine de Saint-Exupéry' -> 'Saint-Exupéry, Antoine de' """
    tokens = name.split()
    suffix = ""
    if len(tokens) > 2 and tokens[-1].lower() in _NAME_SUFFIXES:
        suffix = ", " + tokens.pop()
    if len(tokens) < 2:
        return name
    i = len(tokens) - 1
    while i > 1 and tokens[i - 1].lower() in PARTICLES - _GIVEN_NAME_PARTICLES:
        i -= 1
    return " ".join(tokens[i:]) + ", " + " ".join(tokens[:i]) + suffix


def clean(value):
    """
    A value usable in a file name, also on Windows (copies, Samba): no '/'
    or '\\', ':' -> ' -', no <>"|?* nor control characters, single spaces
    """
    value = unicodedata.normalize("NFC", str(value))
    value = value.replace("/", "-").replace("\\", "-").replace(":", " -")
    value = re.sub(r'[<>"|?*\x00-\x1f\x7f]', "", value)
    return " ".join(value.split())


def _values(book, title, subtitle):
    authors = list(book.authors or [])
    first = authors[0] if authors else ""
    return {
        "title": title,
        "subtitle": subtitle,
        "author": first,
        "authors": first + " et al." if len(authors) > 2 else " & ".join(authors),
        "author_sort": author_sort(first) if first else "",
        "editor": book.editor or "",
        "year": book.year or "",
        "isbn": book.isbn or "",
    }


def _render(pattern, values):
    name = pattern.format(**{k: clean(v) for k, v in values.items()})
    # the parts of the missing values: '()', '[]', a separator left alone
    name = re.sub(r"\(\s*\)|\[\s*\]", "", name)
    parts = []
    for part in re.split(r"\s+-\s+|^-\s+|\s+-$", name):
        part = " ".join(part.split())
        if part.startswith(",") and parts:
            # the value before the comma is missing: 'Title - , 2012' ->
            # 'Title, 2012'
            part = part.strip(" ,;")
            if part:
                parts[-1] += ", " + part
            continue
        part = part.strip(" ,;")
        if part:
            parts.append(part)
    return " - ".join(parts).strip(" .-,;")


def free_name(dirpath, name, own=None):
    """
    name, or 'name (2).pdf', 'name (3).pdf', ... when a file of the
    directory dirpath has it (the convention of the trash); own: the current
    name of the file to rename, which does not count
    """
    stem, ext = os.path.splitext(name)
    for n in range(1, 1000):
        candidate = name if n == 1 else f"{stem} ({n}){ext}"
        if candidate == own or not os.path.lexists(os.path.join(dirpath, candidate)):
            return candidate
    raise NamingError("aucun nom libre")


def file_name(pattern, book):
    """
    The name of the PDF file of a book after the pattern, from its metadata
    in book.db (never from the suggestions), '.pdf' appended. A missing
    value is left out, with its parentheses or separator. Raises NamingError
    when the pattern uses the title and the book has none, or when nothing
    is left.
    """
    names = check_pattern(pattern)
    title = clean(book.title or "")
    if "title" in names and not title:
        raise NamingError("titre manquant")
    subtitle = clean(book.subtitle or "")
    name = _render(pattern, _values(book, title, subtitle))
    # too long: the subtitle is shortened, at a word boundary (left out at
    # last), then the title
    while len((name + SUFFIX).encode("utf-8")) > MAX_NAME_BYTES and (subtitle or " " in title):
        if subtitle:
            subtitle = subtitle.rsplit(" ", 1)[0].rstrip(" ,;:-") if " " in subtitle else ""
        else:
            title = title.rsplit(" ", 1)[0].rstrip(" ,;:-")
        name = _render(pattern, _values(book, title, subtitle))
    if not name:
        raise NamingError("aucune métadonnée pour le nom")
    if len((name + SUFFIX).encode("utf-8")) > MAX_NAME_BYTES:
        raise NamingError("nom trop long")
    return name + SUFFIX
