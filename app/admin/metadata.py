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
Suggestions of metadata for the book page (see srcs/metadata): what to
prefill, what to show next to each field, and the state of the analysis.
"""

from srcs.metadata import analyse, store


def _user_value(book, field):
    """ The value of a field in book.db, None when empty """
    value = getattr(book, field)
    return value or None


def display(field, value):
    """
    A value as set in a field: a list of authors one per line (a candidate
    is a single name)
    """
    if isinstance(value, list):
        return "\n".join(value)
    return str(value)


def _sources(suggestion):
    return ", ".join(analyse.SOURCE_LABELS.get(s, s) for s in suggestion["sources"])


class FieldSuggestion:
    """ The suggestion of a field of the book page """

    def __init__(self, field, suggestion, user_value, prefill):
        self.field = field
        self.value = suggestion["value"]
        self.score = suggestion["score"]
        self.sources = _sources(suggestion)
        self.alternatives = suggestion["alternatives"]
        # set in the empty field of the form
        self.prefilled = prefill and user_value is None
        # shown in a hint, with "Utiliser": the field has another value, or
        # is empty and not prefilled (reviewed book)
        if user_value is None:
            self.differs = not self.prefilled
        else:
            self.differs = not analyse.same_value(field, user_value, self.value)

    @property
    def text(self):
        """ For the hints: authors separated by ';' """
        return "; ".join(self.value) if self.field == "authors" else str(self.value)

    @property
    def form_value(self):
        return display(self.field, self.value)

    @property
    def options(self):
        """ Values of the datalist of the field: suggestion first """
        if self.field == "authors":
            return []
        return list(dict.fromkeys(str(v) for v in [self.value] + self.alternatives))

    @property
    def tooltip(self):
        return f"Suggestion, score {self.score}/100 : {self.sources}"


def suggestions(entry, book, books):
    """
    {field: FieldSuggestion} of a book, from its metadata cache file
    (store.read()), None when there is none. The empty fields are
    prefilled, unless the user has reviewed the book.
    """
    if not entry or entry.get("error") or not entry.get("candidates"):
        return {}
    learned = analyse.Learned.from_books(books)
    found = analyse.suggest(entry["candidates"], book.filename, learned)
    return {f: FieldSuggestion(f, s, _user_value(book, f), not book.meta_reviewed)
            for f, s in found.items()}


def prefill(data, found):
    """ Set the prefilled suggestions in the data of the form """
    for field, s in found.items():
        if s.prefilled:
            data[field] = s.value
    return data


class AnalysisState:
    """ State of the analysis of a book, for the book page """

    def __init__(self, service, book):
        self.entry = service.read(book.sha1)
        self.pending = service.is_pending(book.sha1)
        self.can_run = service.running and book.present
        entry = self.entry
        self.error = entry.get("error") if entry else None
        self.analysed_at = entry.get("analysed_at") if entry else None
        self.outdated = entry is not None and not store.is_current(entry)
        raw = (entry or {}).get("raw") or {}
        self.has_text = raw.get("has_text", True)

    @property
    def message(self):
        if self.pending:
            return "Analyse en cours…"
        if self.entry is None:
            return "PDF pas encore analysé." if self.can_run else "PDF non analysé."
        if self.error:
            return f"Échec de l'analyse : {self.error}"
        when = (self.analysed_at or "").replace("T", " ")[:16]
        message = f"PDF analysé le {when} (UTC)."
        if not self.has_text:
            message += " Peu ou pas de texte (PDF scanné ?) : suggestions limitées."
        if self.outdated:
            message += " Faite par une version précédente, elle sera mise à jour."
        return message

    def candidates(self):
        """ [(field, [[value, source label, weight]], best first)] for the detail """
        cands = (self.entry or {}).get("candidates") or {}
        return [(f, [[display(f, v), analyse.SOURCE_LABELS.get(src, src), w]
                     for v, src, w in sorted(cands[f], key=lambda c: -c[2])])
                for f in analyse.FIELDS if cands.get(f)]

    def texts(self):
        """ [(page number, text)] of the key pages, for the detail """
        raw = (self.entry or {}).get("raw") or {}
        return [(int(k) + 1, t) for k, t in sorted((raw.get("texts") or {}).items(),
                                                   key=lambda kv: int(kv[0])) if t.strip()]
