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
The timeline of the books of interest (/timeline): the reading sessions of
the logged in user, found from the journal of the reader events
(srcs/users/journal.py), drawn along a time line.
"""

import os

from flask import Blueprint, current_app, render_template, url_for

from app.auth import current_user_key, login_required
from srcs.users.journal import SESSION_GAP, reading_sessions

timeline = Blueprint("timeline", __name__)


@timeline.route("/timeline")
@login_required
def timeline_page():
    """ The timeline of the books read by the user """
    events_file = current_app.config.get("READER_EVENTS_FILE")
    found = reading_sessions(events_file, current_user_key()) if events_file else {}
    history = []
    for sha1, sessions in found.items():
        book = current_app.bookdir.find_book_by_sha1(sha1)
        # a book no longer in the library: left out
        if book is None or not book.present:
            continue
        history.append({
            "sha1": sha1,
            "name": os.path.splitext(os.path.basename(book.filename))[0],
            "url": url_for("main.book_reader", sha1=sha1),
            "image": url_for("main.image", sha1=sha1),
            "sessions": [{"start": start.isoformat(), "minutes": round(minutes, 1)}
                         for start, minutes in sessions],
        })
    return render_template("timeline.html", history=history,
                           journal=bool(events_file),
                           session_gap=int(SESSION_GAP.total_seconds() // 60),
                           titre="eBook timeline")
