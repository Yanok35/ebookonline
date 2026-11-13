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
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    url_for,
)

from app.admin.forms import BookForm, ResetThumbnailForm
from app.auth import login_required

admin = Blueprint('admin', __name__)

# Two forms on the book page: distinct field names and ids
RESET_FORM_PREFIX = "reset"


@admin.app_template_filter("datetime")
def format_datetime(timestamp):
    """ {{ book.mtime | datetime }} -> '2026-11-13 21:27' """
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


@admin.route("/bookadmin/")
@login_required
def book_list():
    """ Every book of book.db, including the ones missing from BOOK_DIR """
    books = sorted(current_app.bookdir.get_all_books(),
                   key=lambda b: b.filename.lower())
    return render_template("admin/book_list.html",
                           books=books,
                           nb_missing=sum(not b.present for b in books),
                           titre="eBook admin")


@admin.route("/bookadmin/<sha1>", methods=["GET", "POST"])
@login_required
def bookadmin(sha1):
    """ Book page: file information and user-defined attributes """
    d = current_app.bookdir
    book = d.find_book_by_sha1(sha1)
    if book is None:
        abort(404)

    # Without POST data, the form shows the current values (0: no year)
    form = BookForm(data={
        "tags": book.tags,
        "editor": book.editor,
        "year": book.year or None,
        "isbn": book.isbn,
    })
    if form.validate_on_submit():
        book.tags = form.tags.data
        book.editor = form.editor.data
        book.year = form.year.data or 0
        book.isbn = form.isbn.data or ""
        d.save_db()
        flash("Modifications enregistrées.")
        return redirect(url_for(".bookadmin", sha1=sha1))

    books = d.get_all_books()
    return render_template(
        "admin/book.html",
        book=book,
        form=form,
        reset_form=ResetThumbnailForm(prefix=RESET_FORM_PREFIX),
        library_tags=sorted({t for b in books for t in b.tags.split()}),
        library_editors=sorted({b.editor for b in books if b.editor}),
        copies=d.get_duplicates().get(book.sha1, []),
        titre=f"eBook admin - {os.path.basename(book.filename)}")


@admin.route("/reset-thumbnail/<sha1>", methods=["POST"])
@login_required
def reset_thumbnail(sha1):
    """ Delete the thumbnail of a book, and queue its regeneration """
    d = current_app.bookdir
    book = d.find_book_by_sha1(sha1)
    if book is None:
        abort(404)

    form = ResetThumbnailForm(prefix=RESET_FORM_PREFIX)
    if not form.validate_on_submit():
        flash("Formulaire expiré ou invalide, merci de réessayer.", "error")
    elif not book.present:
        flash("Le PDF est absent du répertoire des livres : "
              "la miniature ne peut pas être régénérée.", "error")
    else:
        thumbname = current_app.cache.get_thumbname(sha1)
        try:
            os.remove(thumbname)
        except FileNotFoundError:
            pass
        pdffile = os.path.join(book.book_dir, book.filename)
        current_app.logger.info("Regenerate thumbnail of '%s'", pdffile)
        current_app.cache.create_thumbnail(pdffile, sha1)
        flash("Miniature en cours de régénération, "
              "recharger la page dans quelques secondes.")

    return redirect(url_for(".bookadmin", sha1=sha1))
