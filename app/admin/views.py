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

import os
from datetime import datetime

from flask import (
    Blueprint,
    current_app,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

from app.auth import login_required

admin = Blueprint('admin', __name__)

@admin.route("/bookadmin/")
@admin.route("/bookadmin/<sha1>", methods=['GET', 'POST'])
@login_required
def bookadmin(sha1 = None):
    d = current_app.bookdir

    bsel = None
    if sha1:
        bsel = d.find_book_by_sha1(sha1)

    edit_book_sha1 = request.values.get('book-sha1')

    if request.method == "POST":
        if 'tags' in request.form.keys():
            bsel.tags = request.form['tags']

        # Write json db
        d.save_db()
        return redirect(url_for(".bookadmin", sha1 = sha1))

    return render_template("bookadmin.html",
                            d = d,
                            bsel = bsel,
                            sha1 = sha1,
                            books = d.get_booklist(),
                            mtimestr = datetime.fromtimestamp(bsel.mtime).strftime('%Y-%m-%d %H:%M:%S'),
                            titre = "eBook admin")

@admin.route("/reset-thumbnail/<sha1>", methods=['POST'])
@login_required
def reset_thumbnail(sha1):
    try:
        current_app.logger.warning(f"get_thumbname = {current_app.cache.get_thumbname(sha1)}")
        os.remove(current_app.cache.get_thumbname(sha1))
    except Exception:
        return make_response(f"Reset thumbnail {sha1} failed !")

    d = current_app.bookdir
    b = d.find_book_by_sha1(sha1)
    pdffile = os.path.join(b.book_dir, b.filename)
    current_app.logger.warning(f"filename= '{pdffile}'")
    current_app.cache.create_thumbnail(pdffile, sha1)
    return redirect(url_for(".bookadmin", sha1 = sha1))
