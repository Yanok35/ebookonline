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
The journal of the reader events (READER_EVENTS_FILE): one JSON line per
saved reading position, appended (append_event()), never rewritten; and
the reading history found from it: the reading sessions of the books.

The reader saves its state 500 ms after each move (scroll, page, zoom) and
at the opening of a book. Events of a book less than SESSION_GAP apart
belong to the same session: from its first to its last event, plus
SESSION_TAIL for the reading of the last page. A page read longer than
SESSION_GAP without moving ends the session (no event meanwhile).
"""

import datetime
import json
import logging

log = logging.getLogger(__name__)

SESSION_GAP = datetime.timedelta(minutes=10)


def append_event(path, sha1, page, user):
    """
    Append a line to the journal path: {"t": time of the server (UTC, ISO
    8601), "doc": sha1 of the book, "page": page, "user": user}. Raises
    OSError.
    """
    event = {
        "t": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "doc": sha1,
        "page": page,
        "user": user,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
SESSION_TAIL = datetime.timedelta(minutes=1)


def read_events(path, user=None):
    """
    [(time, sha1)] of the journal, sorted by time: the events of user (all
    of them when None). A missing file is an empty journal; a malformed
    line (e.g. truncated by a crash) is skipped.
    """
    events = []
    try:
        with open(path, encoding="utf-8") as f:
            for number, line in enumerate(f, 1):
                try:
                    event = json.loads(line)
                    when, sha1 = datetime.datetime.fromisoformat(event["t"]), event["doc"]
                except (ValueError, KeyError, TypeError):
                    log.warning("Reader events %s, line %d: malformed, skipped", path, number)
                    continue
                if when.tzinfo is None:
                    # (written in UTC by the server)
                    when = when.replace(tzinfo=datetime.UTC)
                if user is None or event.get("user") == user:
                    events.append((when, sha1))
    except FileNotFoundError:
        pass
    events.sort(key=lambda e: e[0])
    return events


def sessions(events):
    """
    {sha1: [(start, minutes)]}: the reading sessions of each book, from
    events [(time, sha1)] sorted by time
    """
    out = {}
    current = {}  # sha1 -> [start, last event]
    for when, sha1 in events:
        session = current.get(sha1)
        if session and when - session[1] <= SESSION_GAP:
            session[1] = when
            continue
        if session:
            out.setdefault(sha1, []).append(_closed(session))
        current[sha1] = [when, when]
    for sha1, session in current.items():
        out.setdefault(sha1, []).append(_closed(session))
    return out


def _closed(session):
    start, last = session
    return start, (last - start + SESSION_TAIL).total_seconds() / 60


def reading_sessions(path, user=None):
    """ {sha1: [(start, minutes)]} of the journal path, for user """
    return sessions(read_events(path, user))
