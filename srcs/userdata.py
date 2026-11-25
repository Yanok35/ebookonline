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
The data of the users (USERDATA_DB, "userdata.db"): a JSON file next to
book.db, versioned as it (see docs/technote-userdata.md), kept in memory and
rewritten whole, atomically, after each change. One server process only (as
book.db). For now: the notes of the users in the margin of the books.

    {"version": 1, "min_reader_version": 1,
     "users": {<login>: {"notes": {<sha1>: [{id, page, ratio, quote, text,
                                             created, updated}]}}}}

A file written by a newer version is read, never written (read-only): the
changes are then kept in memory only, as in read-only mode.
"""

import copy
import datetime
import json
import logging
import math
import os
import tempfile
import threading

log = logging.getLogger(__name__)

USERDATA_VERSION = 1
# Oldest schema version whose code can read a file of USERDATA_VERSION
USERDATA_MIN_READER_VERSION = 1

# Migrations: _MIGRATIONS[n] converts the content of version n to n + 1
_MIGRATIONS = [
    # 0 -> 1: the first version
    lambda db: db,
]
assert len(_MIGRATIONS) == USERDATA_VERSION

# Limits of the notes of a book
MAX_NOTES = 1000
MAX_ID = 64
MAX_QUOTE = 256
MAX_TEXT = 10000
MAX_PAGE = 100000


class UserDataError(ValueError):
    """ Invalid data sent (notes), or a file which can not be read """


def _now():
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def clean_notes(notes, previous=()):
    """
    The notes of a book as kept: [{id, page, ratio, quote, text, created,
    updated}], from notes sent by the reader ([{id, page, ratio, quote,
    text}]). The empty ones (no quotation, no text) are dropped. created and
    updated come from the previous notes of the same id when unchanged.
    Raises UserDataError on invalid notes.
    """
    if not isinstance(notes, list):
        raise UserDataError("a list of notes is expected")
    if len(notes) > MAX_NOTES:
        raise UserDataError(f"too many notes: {len(notes)} (at most {MAX_NOTES})")
    before = {n["id"]: n for n in previous}
    now = _now()
    kept = []
    ids = set()
    for note in notes:
        if not isinstance(note, dict):
            raise UserDataError("a note must be an object")
        nid, page, ratio = note.get("id"), note.get("page"), note.get("ratio")
        quote, text = note.get("quote", ""), note.get("text", "")
        if not isinstance(nid, str) or not 0 < len(nid) <= MAX_ID:
            raise UserDataError(f"invalid note id: {nid!r}")
        if nid in ids:
            raise UserDataError(f"note id used twice: {nid!r}")
        ids.add(nid)
        if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= MAX_PAGE:
            raise UserDataError(f"invalid page of note {nid!r}: {page!r}")
        if (not isinstance(ratio, (int, float)) or isinstance(ratio, bool)
                or not math.isfinite(ratio) or not 0 <= ratio <= 1):
            raise UserDataError(f"invalid height of note {nid!r}: {ratio!r}")
        if not isinstance(quote, str) or len(quote) > MAX_QUOTE:
            raise UserDataError(f"invalid quotation of note {nid!r}")
        if not isinstance(text, str) or len(text) > MAX_TEXT:
            raise UserDataError(f"invalid text of note {nid!r} (at most {MAX_TEXT} characters)")
        if not quote and not text.strip():
            continue
        entry = {"id": nid, "page": page, "ratio": float(ratio), "quote": quote, "text": text}
        old = before.get(nid)
        if old is not None:
            unchanged = all(old.get(k) == entry[k] for k in ("page", "ratio", "quote", "text"))
            entry["created"] = old.get("created", now)
            entry["updated"] = old.get("updated", now) if unchanged else now
        else:
            entry["created"] = entry["updated"] = now
        kept.append(entry)
    return kept


class UserData:
    """ The content of USERDATA_DB, in memory """

    def __init__(self, path, read_only=False):
        self.path = path
        self.read_only = read_only
        # Schema version of the file, when newer than USERDATA_VERSION
        self.newer_version = None
        self.lock = threading.RLock()
        self.users = {}
        self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                db = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            raise UserDataError(f"can not read {self.path}: {e}") from None
        if not isinstance(db, dict):
            raise UserDataError(f"can not read {self.path}: an object is expected")
        version = db.get("version", 0)
        if version > USERDATA_VERSION:
            if db.get("min_reader_version", version) > USERDATA_VERSION:
                raise UserDataError(
                    f"{self.path} is version {version}, this is version "
                    f"{USERDATA_VERSION}: upgrade ebookonline")
            log.warning("%s: version %d, newer than %d: read only",
                        self.path, version, USERDATA_VERSION)
            self.newer_version = version
            self.read_only = True
        else:
            for migrate in _MIGRATIONS[version:]:
                db = migrate(db)
        users = db.get("users", {})
        self.users = users if isinstance(users, dict) else {}
        if version < USERDATA_VERSION and not self.read_only:
            log.info("%s: version %d migrated to %d", self.path, version, USERDATA_VERSION)
            self._save()

    def to_json(self):
        return {"version": USERDATA_VERSION,
                "min_reader_version": USERDATA_MIN_READER_VERSION,
                "users": self.users}

    def _save(self):
        """ Written to a temporary file, then renamed: never half written """
        if self.read_only:
            return
        directory = os.path.dirname(os.path.abspath(self.path))
        fd, tmpname = tempfile.mkstemp(prefix=".userdata-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.to_json(), f, ensure_ascii=False, indent=1)
            os.replace(tmpname, self.path)
        finally:
            if os.path.exists(tmpname):
                os.unlink(tmpname)

    # --- notes

    def notes(self, user, sha1):
        """ The notes of user for the book sha1: a copy """
        with self.lock:
            return copy.deepcopy(self.users.get(user, {}).get("notes", {}).get(sha1, []))

    def set_notes(self, user, sha1, notes):
        """
        Replace the notes of user for the book sha1 (see clean_notes()), and
        save. Returns them as kept. Raises UserDataError (invalid notes),
        OSError (not saved: kept in memory).
        """
        with self.lock:
            books = self.users.setdefault(user, {}).setdefault("notes", {})
            kept = clean_notes(notes, books.get(sha1, []))
            if kept:
                books[sha1] = kept
            else:
                books.pop(sha1, None)
            self._save()
            return copy.deepcopy(kept)

    def move_book(self, old_sha1, new_sha1, page_offset=0):
        """
        The notes of a book whose file was replaced in place (a cover page
        added: page_offset 1): moved to its new sha1, their page moved.
        Returns the number of users whose notes moved.
        """
        with self.lock:
            moved = 0
            for data in self.users.values():
                books = data.get("notes", {})
                if old_sha1 not in books:
                    continue
                notes = books.pop(old_sha1)
                for note in notes:
                    note["page"] = max(1, note["page"] + page_offset)
                books[new_sha1] = notes
                moved += 1
            if moved:
                self._save()
            return moved
