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
    session,
    url_for,
)

from app.admin.forms import (
    BookForm,
    MoveBookForm,
    RenameBookForm,
    ResetThumbnailForm,
    RestoreForm,
    TrashBookForm,
    TrashDuplicateForm,
)
from app.auth import login_required
from srcs.book import DB_VERSION
from srcs.bookfileops import ROOT_CATEGORY, BookFileError, list_categories, list_trash

admin = Blueprint('admin', __name__)

# Several forms on the book page: distinct field names and ids
RESET_FORM_PREFIX = "reset"
RENAME_FORM_PREFIX = "rename"
MOVE_FORM_PREFIX = "move"
TRASH_FORM_PREFIX = "trash"

CSRF_ERROR = "Formulaire expiré ou invalide, merci de réessayer."


@admin.context_processor
def read_only_context():
    """ For the banner of the admin pages, when book.db is read-only """
    d = current_app.bookdir
    return {
        "bookdir_read_only": d.read_only,
        "bookdir_db_version": d.db_version,
        "bookdir_supported_version": DB_VERSION,
    }


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
                           duplicates=current_app.bookdir.get_duplicates(),
                           titre="eBook admin")


@admin.route("/bookadmin/duplicates")
@login_required
def duplicates():
    """ The books having duplicates (files with the same content) """
    d = current_app.bookdir
    duplicates = d.get_duplicates()
    books = sorted((b for b in d.get_all_books() if b.sha1 in duplicates),
                   key=lambda b: b.filename.lower())
    return render_template("admin/duplicates.html",
                           duplicate_books=[(b, duplicates[b.sha1]) for b in books],
                           trash_form=TrashDuplicateForm(),
                           titre="eBook admin - doublons")


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
        if d.read_only:
            flash("Base en lecture seule : modifications conservées en mémoire "
                  "seulement, elles seront perdues au redémarrage.", "error")
        else:
            flash("Modifications enregistrées.")
        return redirect(url_for(".bookadmin", sha1=sha1))

    books = d.get_all_books()
    return render_template(
        "admin/book.html",
        book=book,
        form=form,
        reset_form=ResetThumbnailForm(prefix=RESET_FORM_PREFIX),
        rename_form=RenameBookForm(prefix=RENAME_FORM_PREFIX,
                                   data={"name": os.path.basename(book.filename)}),
        move_form=_move_form(data={"category": _category_dir(book)}),
        trash_form=TrashBookForm(prefix=TRASH_FORM_PREFIX),
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


# File operations

def _book_or_404(sha1):
    book = current_app.bookdir.find_book_by_sha1(sha1)
    if book is None:
        abort(404)
    return book


def _flash_form_errors(form):
    if form.csrf_token.errors:
        flash(CSRF_ERROR, "error")
    for field in form:
        if field is not form.csrf_token:
            for error in field.errors:
                flash(f"{field.label.text} : {error}", "error")


def _file_operation(description, operation):
    """
    Run a file operation of the book directory, log and flash its result.
    Returns the result of the operation, None when it was refused.
    """
    user = session.get("username")
    try:
        result = operation()
    except BookFileError as e:
        current_app.logger.warning("%s: %s refused: %s", user, description, e)
        flash(f"Opération refusée : {e}", "error")
        return None
    current_app.logger.warning("%s: %s -> '%s'", user, description, result)
    return result


def _category_dir(book):
    """ The value of the category select for a book ('' for the root) """
    return book.category if "/" in book.filename else ""


def _move_form(**kwargs):
    form = MoveBookForm(prefix=MOVE_FORM_PREFIX, **kwargs)
    form.category.choices = [("", f"{ROOT_CATEGORY} (racine)")] + \
        [(c, c) for c in list_categories(current_app.bookdir.dirpath)]
    return form


@admin.route("/bookadmin/<sha1>/rename", methods=["POST"])
@login_required
def rename_book(sha1):
    book = _book_or_404(sha1)
    form = RenameBookForm(prefix=RENAME_FORM_PREFIX)
    if not form.validate_on_submit():
        _flash_form_errors(form)
    elif _file_operation(f"rename '{book.filename}'",
                         lambda: current_app.bookdir.rename_book(sha1, form.name.data)):
        flash(f"Fichier renommé : {book.filename}")
    return redirect(url_for(".bookadmin", sha1=sha1))


@admin.route("/bookadmin/<sha1>/move", methods=["POST"])
@login_required
def move_book(sha1):
    book = _book_or_404(sha1)
    form = _move_form()
    if not form.validate_on_submit():
        _flash_form_errors(form)
    elif _file_operation(f"move '{book.filename}'",
                         lambda: current_app.bookdir.move_book_to_category(sha1, form.category.data)):
        flash(f"Fichier déplacé : {book.filename}")
    return redirect(url_for(".bookadmin", sha1=sha1))


@admin.route("/bookadmin/<sha1>/trash", methods=["POST"])
@login_required
def trash_book(sha1):
    book = _book_or_404(sha1)
    form = TrashBookForm(prefix=TRASH_FORM_PREFIX)
    if not form.validate_on_submit():
        _flash_form_errors(form)
    else:
        trashed = _file_operation(f"trash '{book.filename}'",
                                  lambda: current_app.bookdir.trash_book(sha1))
        if trashed:
            flash(f"Fichier mis à la corbeille : {trashed}")
    return redirect(url_for(".bookadmin", sha1=sha1))


@admin.route("/bookadmin/duplicates/trash", methods=["POST"])
@login_required
def trash_duplicate():
    form = TrashDuplicateForm()
    if not form.validate_on_submit():
        _flash_form_errors(form)
    else:
        filename = form.filename.data
        trashed = _file_operation(f"trash duplicate '{filename}'",
                                  lambda: current_app.bookdir.trash_duplicate(filename))
        if trashed:
            flash(f"Copie mise à la corbeille : {trashed}")
    return redirect(url_for(".duplicates"))


@admin.route("/bookadmin/trash")
@login_required
def trash():
    """ The PDF files of the trash, which can be restored """
    return render_template("admin/trash.html",
                           files=list_trash(current_app.bookdir.dirpath),
                           restore_form=RestoreForm(),
                           titre="eBook admin - corbeille")


@admin.route("/bookadmin/trash/restore", methods=["POST"])
@login_required
def restore():
    form = RestoreForm()
    if not form.validate_on_submit():
        _flash_form_errors(form)
    else:
        filename = form.filename.data
        restored = _file_operation(f"restore '{filename}'",
                                   lambda: current_app.bookdir.restore_from_trash(filename))
        if restored:
            flash(f"Fichier restauré : {restored}")
    return redirect(url_for(".trash"))
