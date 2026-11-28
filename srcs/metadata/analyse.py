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
Analysis of the raw data of a PDF file (srcs/metadata/extract.py):

1. candidates(): every value found for each field, with its source and a
   weight (how much this source is trusted), e.g. a year after "Dépôt
   légal" weighs 75, the creation date of the file 8;
2. suggest(): the candidates of a field are grouped (same or similar
   values), a group scores the sum of the best weight of each of its
   sources (0 to 100), and the best group gives the suggestion; a close
   second group lowers the score (conflict).

See docs/technote-metadata-extract-&-analysis.md.
"""

import datetime
import difflib
import posixpath
import re
from collections import Counter, defaultdict

from srcs.metadata import publishers
from srcs.metadata.isbn import DIGITAL_CTX, PRINT_CTX, find_isbns, to_isbn13
from srcs.metadata.names import (
    RE_PERSON,
    canonical_person,
    looks_like_person,
    split_authors,
)
from srcs.metadata.text import clean_spaces, fix_case, norm_key, strip_accents

# Version of the rules: incremented when candidates() changes (rules,
# weights, publishers.json). The candidates of the cache files of an older
# version are found again from their raw data, without opening the PDF
# files. suggest() runs on each request: no version.
ANALYSER_VERSION = 2

# The metadata fields, named as the attributes of srcs.library.book.Book
FIELDS = ("title", "subtitle", "authors", "editor", "year", "isbn")

# Sources of the candidates, as shown to the user
SOURCE_LABELS = {
    "meta": "métadonnées du PDF",
    "xmp": "métadonnées XMP",
    "meta-date": "date de création du PDF",
    "legal-deposit": "dépôt légal",
    "printed": "achevé d'imprimer",
    "copyright": "mention ©",
    "first-published": "première publication",
    "text-publisher": "éditeur connu cité dans le texte",
    "text-editions": "« Éditions … » dans le texte",
    "text-published-by": "« Published by … » dans le texte",
    "text-press": "« … Press / Publishing » dans le texte",
    "copyright-name": "nom après ©",
    "title-page": "page de titre",
    "large-font": "plus grande police",
    "by-line": "« par / by … »",
    "isolated-name": "nom seul sur une ligne",
    "filename": "nom du fichier",
    "isbn": "ISBN dans le texte",
    "isbn-prefix": "préfixe ISBN connu",
    "learned-prefix": "préfixe ISBN de vos livres",
}

MIN_YEAR = 1450

RE_COLOPHON = re.compile(
    r"©|\(c\)\s*\d{4}|copyright|isbn|d[ée]p[oô]t\s+l[ée]gal|achev[ée]\s+d.imprimer|tous\s+droits|"
    r"all\s+rights\s+reserved|published\s+by|imprim[ée]\s+en|printed\s+in|première\s+édition|"
    r"first\s+published",
    re.IGNORECASE)
MONTHS = ("janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre"
          "|novembre|décembre|decembre")
RE_DEPOT = re.compile(r"d[ée]p[oô]t\s+l[ée]gal\s*[:\-–]?\s*(?:\d{1,2}(?:er)?\s+)?(?:(?:" + MONTHS
                      + r")\s+|\d{1,2}\s*[/.\-]\s*)?((?:1[5-9]|20)\d{2})", re.IGNORECASE)
RE_ACHEVE = re.compile(r"achev[ée]\s+d.imprimer[^\n]{0,120}?((?:1[5-9]|20)\d{2})", re.IGNORECASE | re.DOTALL)
RE_COPY_YEAR = re.compile(
    r"(?:©|\(c\)|copyright)\s*(?:©\s*)?(?:[^\n\d]{0,60}?)((?:1[5-9]|20)\d{2})(?!\d)", re.IGNORECASE)
RE_FIRST_PUB = re.compile(r"(?:first\s+published|published\s+in|premi[èe]re\s+[ée]dition|"
                          r"[ée]dition\s+originale|publi[ée]\s+(?:pour\s+la\s+premi[èe]re\s+fois\s+)?en)"
                          r"[^\n\d]{0,40}((?:1[5-9]|20)\d{2})", re.IGNORECASE)
RE_PUB_EDITIONS = re.compile(
    r"\b((?:Les\s+)?[ÉE]ditions\s+(?:de\s+la\s+|de\s+l['’]|du\s+|des\s+|de\s+)?"
    r"[A-ZÀ-Þ][\w'’\-]+(?:\s+(?:&\s+)?[A-ZÀ-Þ][\w'’\-]+){0,2})")
RE_PUB_BY = re.compile(
    r"published\s+(?:in\s+[^\n]{0,40}?\s+)?by\s+([A-Z][\w&.'’\- ]{2,60}?)(?:,|\.|\n|\s+in\s|\s+an\s)",
    re.IGNORECASE)
RE_PUB_SUFFIX = re.compile(
    r"\b([A-Z][\w'’\-]+(?:\s+[A-Z&][\w'’\-]*){0,3}\s+(?:Press|Publishing|Publishers|Books|Verlag))\b")
RE_TRANSLATOR = re.compile(
    r"(?:tradu\w*|translated|adapt[ée]\w*)[^\n]{0,60}?\b(?:par|by)\s+(" + RE_PERSON.pattern + ")",
    re.IGNORECASE)
RE_COPY_NAME = re.compile(
    r"(?:©|\(c\)|copyright)\s*(?:©\s*)?(?:(?:1[5-9]|20)\d{2}\s*(?:[,\-–]\s*(?:1[5-9]|20)\d{2})?\s*,?\s*)?"
    r"(?:by\s+|pour\s+le\s+texte\s*:?\s*)?(" + RE_PERSON.pattern + ")")
RE_BY = re.compile(r"(?:^|\n)\s*(?:by|par)\s+(" + RE_PERSON.pattern + r")\s*(?:\n|$)")
RE_SAME_AUTHOR = re.compile(
    r"du\s+m[êe]me\s+auteur|also\s+by|dans\s+la\s+m[êe]me\s+collection", re.IGNORECASE)

# Useless values of the metadata of a PDF file (software, placeholders)
RE_JUNK_META = re.compile(
    r"unknown|inconnu|anonymous|anonyme|^user$|admin|owner|calibre|adobe|microsoft|acrobat|pdf|"
    r"scanner|^\W*$|www\.|http|@|\.docx?$|\.indd$|\.qxd|untitled|sans titre|document\d*$|^doc\d|"
    r"^book\d*$|^titre$|^title$", re.IGNORECASE)

# Noise of the file names of downloaded books
RE_FILENAME_JUNK = re.compile(
    r"[\[({][^\])}]*(?:z-?lib|libgen|epub|pdf|mobi|ebook|retail|scan|ocr|v\d|french|fr|eng|"
    r"vf|\d{4}|isbn|bibliotik|annas?)[^\])}]*[\])}]|\b(?:z-library|libgen|ebook|epub|retail)\b",
    re.IGNORECASE)


def plausible_meta(s, maxlen=200):
    s = clean_spaces(s)
    return bool(s) and 1 < len(s) <= maxlen and not RE_JUNK_META.search(s)


def clean_filename_stem(stem):
    s = stem
    if " " not in s and ("_" in s or "." in s):
        s = s.replace(".", " ")
    s = s.replace("_", " ")
    s = RE_FILENAME_JUNK.sub(" ", s)
    s = re.sub(r"\b97[89]\d{10}\b|\b\d{9}[\dXx]\b", " ", s)
    return re.sub(r"\s+", " ", s).strip(" -–_.,")


class Candidates:
    """ {field: [[value, source, weight]]}, saved as is in the cache file """

    def __init__(self):
        self.fields = defaultdict(list)

    def add(self, field, value, source, weight):
        if value is None:
            return
        if isinstance(value, str):
            value = clean_spaces(value).strip(" ,;:-–")
            if not value:
                return
        self.fields[field].append([value, source, weight])


def _valid_year(year, current_year):
    return MIN_YEAR <= year <= current_year + 1


# Lines of a title page which are not a subtitle: a web site, a publisher
# city, a legal mention
RE_NOT_SUBTITLE_LINE = re.compile(
    r"www\.|https?:|@|copyright|©|isbn|d[ée]p[oô]t|birmingham|beijing|cambridge|new york|london|"
    r"paris\b|publish|\bpress\b|[ée]ditions\b", re.IGNORECASE)
# Spaced letters ('A L L - I N - O N E'): a decoration, not a subtitle
RE_SPACED_LETTERS = re.compile(r"^(?:\S\s){3,}")


def _join_lines(lines):
    """ The lines of a text, the words cut by a hyphen ('mind-', 'blowing') joined """
    text = ""
    for line in lines:
        text = text + line if text.endswith("-") and not text.endswith(" -") else text + " " + line
    return clean_spaces(text)


def title_page_subtitle(lines, in_title, referential, authors=()):
    """
    (subtitle, its lines) of a title page ([[font size, line]], in the reading
    order), or '': the lines after the title (in_title(size): a line of the
    title), in the same smaller font size, an edition between them skipped;
    ends at a name of person (or one of authors, comparison keys), a
    separator ('—'), a publisher, a city. A line which ends with a lowercase
    word or a comma is continued by the next one, even if it looks like a
    name ('Mastering Basic Algorithms in the' / 'Python Language').
    ('', []) without a subtitle.
    """
    last = max((i for i, (size, _) in enumerate(lines) if in_title(size)), default=None)
    if last is None:
        return "", []
    parts, part_size = [], None
    for size, line in lines[last + 1:]:
        line = clean_spaces(line)
        if in_title(size):
            break  # the title again
        if part_size is None and RE_NOT_SUBTITLE.match(line):
            continue  # 'Second Edition' between the title and the subtitle
        if part_size is not None and abs(size - part_size) > 0.5:
            break
        continued = bool(parts) and re.search(r"(?:\b[a-zà-ÿ]\w*|[,\-])$", parts[-1])
        name = canonical_person(re.sub(r"^(?:by|par|de|dr\.?|prof\.?)\s+", "", line,
                                       flags=re.IGNORECASE))
        if (re.fullmatch(r"[\d\W]*", line) or RE_NOT_SUBTITLE_LINE.search(line)
                or RE_SPACED_LETTERS.match(line) or RE_NOT_SUBTITLE.match(line)
                or norm_key(name) in authors or referential.is_known(line)
                or (not continued and looks_like_person(name, referential))):
            break
        parts.append(line)
        part_size = size
        if len(parts) > 4:
            return "", []  # body text, not a subtitle
    subtitle = _join_lines(parts).strip(" .,;:")
    return (subtitle, parts) if 3 <= len(subtitle) <= 200 else ("", [])


def candidates(raw, referential=None):
    """
    {field: [[value, source, weight]]}: the candidate values found in the
    raw data of a PDF file (see extract.extract()). The authors candidates
    are single names; the ISBN ones are ISBN-13. They only depend on the
    content of the file (see filename_candidates()).
    """
    referential = referential or publishers.default()
    current_year = datetime.date.today().year
    c = Candidates()
    meta, xmp = raw.get("meta") or {}, raw.get("xmp") or {}
    texts = {int(k): v or "" for k, v in (raw.get("texts") or {}).items()}
    is_calibre = "calibre" in (meta.get("producer", "") + meta.get("creator", "")).lower() \
        or xmp.get("calibre")
    first_pages = sorted(texts)[:6]

    # --- metadata of the document ---
    meta_weight = 45 if is_calibre else 35
    t = meta.get("title", "")
    if plausible_meta(t) and not re.search(r"\.(?:pdf|epub|docx?|rtf|txt)$", t, re.IGNORECASE):
        c.add("title", fix_case(t), "meta", meta_weight)
    au = meta.get("author", "")
    if plausible_meta(au, 150):
        for p in split_authors(au):
            if 1 < len(p) <= 60:
                c.add("authors", p, "meta", meta_weight)
    for x in xmp.get("dc:title", [])[:1]:
        if plausible_meta(x):
            c.add("title", fix_case(x), "xmp", 50)
    for x in xmp.get("dc:creator", [])[:4]:
        if plausible_meta(x, 150):
            for p in split_authors(x):
                c.add("authors", p, "xmp", 50)
    for x in xmp.get("dc:publisher", [])[:1]:
        if plausible_meta(x, 100):
            c.add("editor", referential.canonical(x), "xmp", 50)
    for x in xmp.get("dc:date", [])[:2]:
        m = re.search(r"(1[5-9]|20)\d{2}", x)
        # calibre writes 0101-01-01 for an unknown date
        if m and not x.startswith("0101") and _valid_year(int(m.group(0)), current_year):
            c.add("year", int(m.group(0)), "xmp", 50)
    meta_isbns = set(xmp.get("isbns", []))
    for k in ("subject", "keywords", "title"):
        meta_isbns |= {hit.isbn13 for hit in find_isbns(meta.get(k, ""))}
    if not is_calibre:
        m = re.search(r"D?:?((?:19|20)\d{2})", meta.get("creationdate", ""))
        if m and int(m.group(1)) <= current_year:
            c.add("year", int(m.group(1)), "meta-date", 8)

    # --- text of the key pages ---
    translators = set()
    isbn_hits = defaultdict(lambda: {"weight": 0.0, "count": 0})
    for i, txt in texts.items():
        if not txt.strip():
            continue
        colophon = bool(RE_COLOPHON.search(txt))
        for m in RE_TRANSLATOR.finditer(txt):
            translators.add(norm_key(canonical_person(m.group(1))))
        hits = find_isbns(txt)
        # a catalog page, or a list of the books of the same author
        listing = len({h.isbn13 for h in hits}) > 3
        same_author = bool(RE_SAME_AUTHOR.search(txt))
        for hit in hits:
            w = (30 if hit.labelled else 12) + (20 if colophon else 0)
            if DIGITAL_CTX.search(hit.context):
                w += 6
            elif PRINT_CTX.search(hit.context):
                w += 3
            if same_author:
                w -= 10
            if listing:
                w *= 0.3
            if i in first_pages:
                w += 5
            isbn_hits[hit.isbn13]["weight"] = max(isbn_hits[hit.isbn13]["weight"], w)
            isbn_hits[hit.isbn13]["count"] += 1
        if not colophon:
            continue
        for m in RE_DEPOT.finditer(txt):
            c.add("year", int(m.group(1)), "legal-deposit", 75)
        for m in RE_ACHEVE.finditer(txt):
            c.add("year", int(m.group(1)), "printed", 45)
        years = [int(m.group(1)) for m in RE_COPY_YEAR.finditer(txt)]
        years = [y for y in years if _valid_year(y, current_year)]
        if years:
            c.add("year", max(years), "copyright", 50)
        for m in RE_FIRST_PUB.finditer(txt):
            c.add("year", int(m.group(1)), "first-published", 20)
        for canon, around in referential.search(txt):
            # on a line with ©, éditions, published, ...
            bonus = 10 if re.search(r"©|copyright|[ée]ditions?|published|\(c\)|isbn",
                                    strip_accents(around), re.IGNORECASE) else 0
            c.add("editor", canon, "text-publisher", 35 + bonus)
        for m in RE_PUB_EDITIONS.finditer(txt):
            name = referential.canonical(m.group(1))
            if len(name) > 10 and not re.search(r"originale?|num[ée]rique|revue|pr[ée]c[ée]dente",
                                                name, re.IGNORECASE):
                c.add("editor", name, "text-editions", 30)
        for m in RE_PUB_BY.finditer(txt):
            c.add("editor", referential.canonical(m.group(1)), "text-published-by", 35)
        for m in RE_PUB_SUFFIX.finditer(txt):
            name = m.group(1)
            if not re.match(r"(?:The|All|No|Our|Other)\s", name) or "No Starch" in name:
                c.add("editor", referential.canonical(name), "text-press", 25)
        for m in RE_COPY_NAME.finditer(txt):
            name = canonical_person(m.group(1))
            if looks_like_person(name, referential) and norm_key(name) not in translators:
                c.add("authors", name, "copyright-name", 35)

    # --- title page: the text in the largest font, and the names of persons
    # of the same page ---
    title_page, big_title = None, None
    for page, lines in raw.get("fonts") or []:
        good = [(size, t) for size, t in lines
                if 2 <= len(t) <= 120
                and not re.search(r"^[\d\W]+$|copyright|©|isbn|d[ée]p[oô]t", t, re.IGNORECASE)]
        if not good:
            continue
        largest = max(size for size, _ in good)
        sizes = {size for size, _ in good}
        if largest < 13 or (len(sizes) == 1 and len(good) > 6):
            continue  # a page of body text, in a single font size
        tolerance = 0.92
        top = [t for size, t in good if size >= largest * tolerance]
        title = clean_spaces(" ".join(top))
        if not 2 <= len(title) <= 150:
            continue
        others = [canonical_person(re.sub(r"^(?:by|par|de)\s+", "", t, flags=re.IGNORECASE))
                  for size, t in good if size < largest * tolerance]
        names = [n for n in others
                 if looks_like_person(n, referential) and norm_key(n) not in translators]
        def in_title(size):
            return size >= largest * tolerance
        if looks_like_person(title, referential) and not names:
            # the largest text is a name: the author, the title is the next
            # largest text
            smaller = [size for size, t in good if size < largest * tolerance]
            if smaller:
                c.add("authors", canonical_person(title), "title-page", 30)
                title_size = max(smaller)
                title = clean_spaces(" ".join(t for size, t in good if size == title_size))

                def in_title(size):
                    return size == title_size
        subtitle, subtitle_lines = title_page_subtitle(
            lines, in_title, referential, {norm_key(v) for v, _, _ in c.fields.get("authors", [])})
        # the lines of the subtitle are not names ('Python Language' of
        # 'Mastering Basic Algorithms in the' / 'Python Language')
        not_names = {norm_key(canonical_person(t)) for t in subtitle_lines}
        names = [n for n in names if norm_key(n) not in not_names]
        title_page, big_title = int(page), title
        source = "title-page" if names else "large-font"
        c.add("title", fix_case(title), source, 50 if names else 30)
        if subtitle:
            # with the title of the page: see subtitle_candidates()
            c.add("subtitle", fix_case(subtitle), source, 40 if names else 25)
        for name in names[:3]:
            c.add("authors", name, "title-page", 50)
        break

    for i in first_pages[:5]:
        txt = texts.get(i, "")
        for m in RE_BY.finditer(txt):
            name = canonical_person(m.group(1))
            if looks_like_person(name, referential) and norm_key(name) not in translators:
                c.add("authors", name, "by-line", 25)
        if i == title_page:
            continue
        for line in txt.splitlines()[:40]:
            line = clean_spaces(line)
            if looks_like_person(line, referential) \
                    and norm_key(canonical_person(line)) not in translators \
                    and norm_key(line) != norm_key(big_title or ""):
                c.add("authors", canonical_person(line), "isolated-name", 8)

    # --- ISBN ---
    for i13 in meta_isbns:
        isbn_hits[i13]["weight"] += 50
    for i13, hit in isbn_hits.items():
        # a few more occurrences add a little
        c.add("isbn", i13, "isbn",
              min(100, hit["weight"] + 4 * max(0, min(hit["count"] - 1, 3))))
    if isbn_hits:
        best = max(isbn_hits.items(), key=lambda kv: kv[1]["weight"])[0]
        name = referential.by_prefix(best)
        if name:
            c.add("editor", name, "isbn-prefix", 40)

    return dict(c.fields)


def filename_candidates(filename, referential=None):
    """
    {field: [[value, source, weight]]}: the candidates found in the name of
    a PDF file (path relative to the book directory): 'Author - Title', or
    the title. Not saved in the cache: the file can be renamed.
    """
    referential = referential or publishers.default()
    c = Candidates()
    stem = clean_filename_stem(posixpath.splitext(posixpath.basename(filename))[0])
    parts = [p.strip() for p in re.split(r"\s+[-–—]\s+", stem) if p.strip()]
    if len(parts) >= 2:
        for p in parts:
            if looks_like_person(canonical_person(p), referential):
                c.add("authors", canonical_person(p), "filename", 25)
            else:
                c.add("title", p, "filename", 15)
    elif stem:
        c.add("title", stem, "filename", 15)
    return dict(c.fields)


# --- consolidation ---

def _group_key(field, value, referential):
    if field == "authors":
        return " ".join(sorted(norm_key(value).split()))
    if field == "year":
        return str(value)
    if field == "editor":
        return norm_key(referential.canonical(value))
    return norm_key(value)


def _similar(field, k1, k2):
    if field in ("year", "isbn"):
        return k1 == k2
    if k1 == k2:
        return True
    if field == "title" and min(len(k1), len(k2)) >= 5 and (k1.startswith(k2) or k2.startswith(k1)):
        return True
    return difflib.SequenceMatcher(None, k1, k2).ratio() >= (0.9 if field == "authors" else 0.88)


# What follows a title in a longer form of it, when it is an addition: an
# edition, a subtitle, a volume (', 2nd Edition', ': Mastering ...')
RE_TITLE_ADDITION = re.compile(r"\s*(?:[,:;(\[/.]|[-–—]\s)")


def _is_title_addition(short, long):
    """
    True when long is short followed by an addition to remove: after a
    punctuation, or long enough (short is at least half of long). Not for a
    title cut short ('Python' of 'Python In A Nutshell', its title page in
    two font sizes).
    """
    if not norm_key(long).startswith(norm_key(short)):
        return False
    if long.casefold().startswith(short.casefold()) \
            and RE_TITLE_ADDITION.match(long[len(short):]):
        return True
    return len(norm_key(short)) >= len(norm_key(long)) / 2


def shortest_title(values):
    """
    The title of a group of similar candidates ([(value, weight)]), among
    the best sources (80% of the best weight): the shortest one, unless it
    is a title cut short of a longer one of these sources (then the longer
    one: e.g. the title page in two font sizes), and a shorter form only
    when what it removes is an addition (see _is_title_addition()). The
    weaker sources (file name) are not used to lengthen a title: they
    often add a subtitle, an author, a publisher.
    """
    top_weight = max(w for _, w in values)
    top = sorted({v for v, w in values if w >= top_weight * 0.8}, key=len)
    best_weight = sorted((v for v, w in values if w == top_weight), key=len)
    best = best_weight[0]
    # 'Python' of 'Python In A Nutshell': the full title
    cut = [v for v in top if len(v) > len(best)
           and norm_key(v).startswith(norm_key(best)) and not _is_title_addition(best, v)]
    if cut:
        best = cut[-1]
    for value in top:
        if value == best or _is_title_addition(value, best):
            return value
    return best


# Between a title and its subtitle: 'Python Algorithms: Mastering ...'
RE_SUBTITLE_SEP = re.compile(r"\s*:\s+|\s+[-–—]\s+")
# What follows a title without being a subtitle: an edition, a volume
RE_NOT_SUBTITLE = re.compile(
    r"(?:\d+\s*(?:st|nd|rd|th|e|ème|eme|ère|ere|er)?|first|second|third|fourth|fifth|sixth|"
    r"seventh|eighth|ninth|tenth|new|revised|updated|expanded|nouvelle|deuxième|troisième)?\s*"
    r"(?:edition|édition|ed\.|éd\.)(?!\w)|(?:vol(?:ume)?|tome|part|partie|book|livre)\.?\s*"
    r"(?:\d+|[IVX]+)\W*$", re.IGNORECASE)
# A series at the end of a subtitle: '... (World Scientific Series ...)'
RE_SERIES = re.compile(r"\s*[(\[][^()\[\]]*[)\]]\s*$")


def same_value(field, user, suggested):
    """ True when a value of book.db is the suggested one (case, accents, ISBN-10) """
    if field == "authors":
        return [norm_key(n) for n in user] == [norm_key(n) for n in suggested]
    if field == "year":
        return user == suggested
    if field == "isbn":
        return (to_isbn13(user) or user) == suggested
    return norm_key(user) == norm_key(suggested)


def split_title(value):
    """
    (title, subtitle) of a title: ('Python Algorithms', 'Mastering Basic
    Algorithms') of 'Python Algorithms: Mastering Basic Algorithms', the
    series at the end left out. (value, '') without a subtitle, or when what
    follows the separator is an edition or a volume.
    """
    m = RE_SUBTITLE_SEP.search(value)
    if not m:
        return value, ""
    title, subtitle = value[:m.start()].strip(), value[m.end():].strip()
    subtitle = RE_SERIES.sub("", subtitle).strip(" .,;:")
    if len(title) < 2 or not norm_key(title) or not subtitle or RE_NOT_SUBTITLE.match(subtitle):
        return value, ""
    return title, subtitle


# Sources of a subtitle found with a title, on the title page
TITLE_PAGE_SOURCES = ("title-page", "large-font")


def subtitle_candidates(title_candidates, title, page_subtitles=()):
    """
    [[subtitle, source, weight]] of the title candidates (but the file
    name, whose parts are often an author or a publisher) made of the title
    and a subtitle, and the subtitles of the title page (page_subtitles)
    when the title of the page is the title
    """
    key = norm_key(title)
    page_titles = [norm_key(split_title(v)[0]) for v, source, _ in title_candidates
                   if source in TITLE_PAGE_SOURCES]
    found = [list(c) for c in page_subtitles
             if any(k and _similar("title", k, key) for k in page_titles)
             # not the end of the title: the title page in two font sizes
             and norm_key(c[0]) not in key]
    for value, source, weight in title_candidates:
        if source == "filename":
            continue
        t, subtitle = split_title(value)
        if subtitle and norm_key(t) == key:
            found.append([subtitle, source, weight])
    return found


def consolidate(field, field_candidates, referential=None):
    """
    {'value', 'score', 'sources', 'alternatives'} of a field, or None
    without candidate. 'value' is a list of names for the authors; 'sources'
    are the sources of the value, best first.
    """
    referential = referential or publishers.default()
    groups = []  # [key, {source: best weight}, [(value, weight)]]
    for value, source, weight in field_candidates:
        key = _group_key(field, value, referential)
        if not key:
            continue
        for g in groups:
            if _similar(field, g[0], key):
                g[1][source] = max(g[1].get(source, 0), weight)
                g[2].append((value, weight))
                break
        else:
            groups.append([key, {source: weight}, [(value, weight)]])
    if not groups:
        return None
    scored = sorted(((min(100, sum(g[1].values())), g) for g in groups), key=lambda x: -x[0])

    def best_value(g):
        # best weight first, the longest one on a tie
        values = sorted(g[2], key=lambda x: (-x[1], -len(str(x[0]))))
        if field == "title":
            return shortest_title(values)
        return values[0][0]

    def sources(g):
        return [s for s, _ in sorted(g[1].items(), key=lambda x: -x[1])]

    if field == "authors":
        top = scored[0][0]
        # several authors: the names scoring almost as much as the first one
        keep = [s for s in scored if s[0] >= max(30, top * 0.75)][:4]
        return {
            "value": [best_value(g) for _, g in keep],
            "score": int(top),
            "sources": list(dict.fromkeys(s for _, g in keep for s in sources(g))),
            "alternatives": [best_value(g) for _, g in scored[len(keep):len(keep) + 3]],
        }
    score, g1 = scored[0]
    if len(scored) > 1 and scored[1][0] >= 0.8 * score:
        score = int(score * 0.7)  # conflict between serious candidates
    return {
        "value": best_value(g1),
        "score": int(score),
        "sources": sources(g1),
        "alternatives": [best_value(g) for _, g in scored[1:4]],
    }


class Learned:
    """
    What is learned from the values entered by the user in book.db (never
    from suggestions): the ISBN prefixes of the publishers, and the user
    spelling of each publisher, which replaces the canonical one.
    """

    def __init__(self, prefixes=None, editors=None):
        self.prefixes = prefixes or {}
        # {comparison key of the canonical name: user spelling}
        self.editors = editors or {}

    @classmethod
    def from_books(cls, books, referential=None):
        referential = referential or publishers.default()
        pairs = []
        spellings = defaultdict(Counter)
        # the canonical name of each spelling, once: a library has few of
        # them, and canonical() searches every alias of the referential
        keys = {}
        for b in books:
            if not b.editor:
                continue
            if b.editor not in keys:
                keys[b.editor] = norm_key(referential.canonical(b.editor))
            spellings[keys[b.editor]][b.editor] += 1
            isbn13 = to_isbn13(b.isbn)
            if isbn13:
                pairs.append((isbn13, b.editor))
        return cls(publishers.learn_prefixes(pairs),
                   {key: c.most_common(1)[0][0] for key, c in spellings.items()})


def suggest(field_candidates, filename=None, learned=None, referential=None):
    """
    {field: suggestion} (see consolidate()) of the candidates of a book
    (from its cache file), of its file name, and of what is learned from
    book.db, for the fields having candidates
    """
    referential = referential or publishers.default()
    field_candidates = {f: list(v) for f, v in field_candidates.items()}
    if filename:
        for f, v in filename_candidates(filename, referential).items():
            field_candidates.setdefault(f, []).extend(v)
    suggestions = {}
    for field in ("isbn",) + tuple(f for f in FIELDS if f != "isbn"):
        if field == "editor" and learned and learned.prefixes and "isbn" in suggestions:
            name = publishers.prefix_lookup(learned.prefixes, suggestions["isbn"]["value"])
            if name:
                # replaces the prefix of publishers.json
                field_candidates["editor"] = [
                    c for c in field_candidates.get("editor", []) if c[1] != "isbn-prefix"]
                field_candidates["editor"].append([name, "learned-prefix", 45])
        if field == "subtitle":
            if "title" not in suggestions:
                continue
            cands = subtitle_candidates(field_candidates.get("title", []),
                                        suggestions["title"]["value"],
                                        field_candidates.get("subtitle", []))
        else:
            cands = field_candidates.get(field, [])
        s = consolidate(field, cands, referential)
        if s is None:
            continue
        if field == "title":
            # the subtitle is suggested in its own field
            s["value"] = split_title(s["value"])[0]
        if field == "editor" and learned:
            s["value"] = learned.editors.get(norm_key(referential.canonical(s["value"])), s["value"])
        suggestions[field] = s
    return {f: suggestions[f] for f in FIELDS if f in suggestions}
