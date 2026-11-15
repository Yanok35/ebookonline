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

""" Names of persons (authors): recognition, canonical form, lists """

import re

from srcs.metadata import publishers
from srcs.metadata.text import clean_spaces, norm_key

PARTICLES = {"de", "du", "des", "d'", "d’", "von", "van", "der", "den", "le", "la", "di",
             "da", "del", "della", "y", "ibn", "ben", "bin", "al", "el", "ter", "zu",
             "dos", "das"}

# Words which are not part of a name (headings, publishing words, ...)
NOT_NAME_WORDS = {norm_key(w) for w in """
table matières matieres sommaire préface preface introduction avant-propos chapitre chapter partie part
tome volume livre book roman novel nouvelles collection édition edition éditions editions copyright
tous droits réservés all rights reserved published publié imprimé printed france paris london new york
traduit traduction translated translation illustrations couverture cover remerciements acknowledgments
du même auteur also by the le la les des un une et and of in à au aux pour for with avec sur
présente presents dans série series prix poche folio pocket notes index bibliographie bibliography
contents dédicace prologue épilogue epilogue conclusion annexe appendix glossaire glossary lexique
press books publishing publishers group library university université presses media inc ltd sa sas
imprimerie dépôt depot légal legal isbn achevé impression maquette conception photo photographie
saint mont rue avenue boulevard cedex tél tel www http com fr org net pdf epub ebook calibre unknown
inconnu auteur author anonymous anonyme user admin owner microsoft word adobe acrobat untitled sans titre
""".split()}  # noqa: SIM905

# 'Hugo', 'Saint-Exupéry', 'HUGO', 'J.' or 'J.-P.'
# (Latin Extended-A letters, both cases, for 'Milovanović', 'Dvořák'; 'Mc'
# and 'Mac' before a capital, for 'McKinney')
RE_NAME_TOKEN = (r"(?:(?:Mc|Mac)?[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿĀ-ſ'’]+(?:-[A-ZÀ-ÖØ-Þ]?[a-zà-öø-ÿĀ-ſ'’]+)*"
                 r"|[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ'’\-]+"
                 r"|[A-ZÀ-ÖØ-Þ]\.(?:-?[A-ZÀ-ÖØ-Þ]\.)?)")
# An initial: 'A.' is not the article 'a'
RE_INITIAL = re.compile(r"[A-ZÀ-ÖØ-Þ]\.(?:-?[A-ZÀ-ÖØ-Þ]\.)?")
RE_PERSON = re.compile(
    RE_NAME_TOKEN + r"(?:\s+(?:(?:de|du|des|von|van|der|den|le|la|di|da|del|y|ibn|ben|al|el)\s+|d['’])?"
    + RE_NAME_TOKEN + r"){1,3}")


def looks_like_person(s, referential=None):
    """ True for 'Victor Hugo', 'J. R. R. Tolkien'; False for 'Table des matières' """
    s = clean_spaces(s)
    if not s or len(s) > 50 or re.search(r"\d|@|/|\\|_", s):
        return False
    tokens = s.split()
    if not 2 <= len(tokens) <= 5:
        return False
    real = [t for t in tokens if t.lower() not in PARTICLES]
    if len(real) < 2:
        return False
    for t in real:
        if norm_key(t) in NOT_NAME_WORDS and not RE_INITIAL.fullmatch(t):
            return False
        if not re.fullmatch(RE_NAME_TOKEN, t.replace("d’", "").replace("d'", "")) \
                and not re.fullmatch(r"d['’]" + RE_NAME_TOKEN, t):
            return False
    return not (referential or publishers.default()).is_known(s)


def canonical_person(s):
    """ 'HUGO, Victor' -> 'Victor Hugo'; 'VICTOR HUGO' -> 'Victor Hugo' """
    s = clean_spaces(s).strip(" ,;.")
    s = re.sub(r"\s*\((?:auteur|author|ed\.?|éd\.?|dir\.?|trad\.?)\)\s*$", "", s, flags=re.IGNORECASE)
    if s.count(",") == 1:
        a, b = [x.strip() for x in s.split(",")]
        if a and b and len(a.split()) <= 3 and len(b.split()) <= 3 \
                and not re.search(r"\b(jr|sr|ii|iii)\b", b, re.IGNORECASE):
            s = f"{b} {a}"

    def fix_token(t):
        # 'HUGO' -> 'Hugo', 'SAINT-EXUPÉRY' -> 'Saint-Exupéry'; 'J.R.R.' kept
        if len(t) > 1 and t.isupper() and "." not in t:
            if t.lower() in PARTICLES:
                return t.lower()
            return "-".join(x[:1] + x[1:].lower() for x in t.split("-"))
        return t

    return " ".join(fix_token(t) for t in s.split())


def split_authors(s):
    """ 'A & B', 'A; B', 'A, B, C', 'A and B' -> [canonical names] """
    s = clean_spaces(s)
    if not s:
        return []
    if ";" in s:
        parts = s.split(";")
    elif re.search(r"\s(?:&|and|et|und|y)\s", s):
        if s.count(",") != 1:
            parts = re.split(r"\s(?:&|and|et|und|y)\s|,\s*", s)
        else:
            parts = re.split(r"\s(?:&|and|et|und|y)\s", s)
    elif s.count(",") >= 2:
        parts = s.split(",")
    else:
        parts = [s]
    return [canonical_person(p) for p in parts if p.strip()]
