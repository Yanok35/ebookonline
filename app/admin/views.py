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
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.exceptions import RequestEntityTooLarge

from app.admin import metadata
from srcs import naming, pdfstats
from srcs.cache import available_backends
from srcs.transformations import CoverPage
from srcs.metadata.service import TASK_TIMEOUT
from app.admin.forms import (
    AnalyseForm,
    BookForm,
    CoverForm,
    DeleteFromTrashForm,
    EmptyTrashForm,
    MoveBookForm,
    RenameBookForm,
    ResetThumbnailForm,
    THUMBNAIL_BACKEND_LABELS,
    RestoreForm,
    RestoreOriginalForm,
    TrashBookForm,
    TrashDuplicateForm,
)
from app import is_read_only
from app.api import move_reader_state
from app.auth import login_required
from srcs.bookfileops import (
    ROOT_CATEGORY,
    BookFileError,
    delete_from_trash,
    empty_trash,
    list_categories,
    list_trash,
)

admin = Blueprint('admin', __name__)

# Several forms on the book page: distinct field names and ids
RESET_FORM_PREFIX = "reset"
ANALYSE_FORM_PREFIX = "analyse"
RENAME_FORM_PREFIX = "rename"
COVER_FORM_PREFIX = "cover"
MOVE_FORM_PREFIX = "move"
TRASH_FORM_PREFIX = "trash"
ORIGINAL_FORM_PREFIX = "original"

CSRF_ERROR = "Formulaire expiré ou invalide, merci de réessayer."


@admin.app_template_filter("datetime")
def format_datetime(timestamp):
    """ {{ book.mtime | datetime }} -> '2026-11-13 21:27' """
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


@admin.app_template_filter("filesize")
def format_filesize(n):
    """ {{ 1536 | filesize }} -> '1.5 Ko'; Mo above a MiB """
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f}\u00a0Mo"
    return f"{n / 1024:.1f}\u00a0Ko"


@admin.route("/bookadmin/")
@login_required
def book_list():
    """ Every book of book.db, including the ones missing from BOOK_DIR """
    books = sorted(current_app.bookdir.get_all_books(),
                   key=lambda b: b.filename.lower())
    return render_template("admin/book_list.html",
                           books=books,
                           nb_missing=sum(not b.present for b in books),
                           # present books only (a missing book has no size)
                           total_size=sum(b.filesize for b in books if b.present),
                           duplicates=current_app.bookdir.get_duplicates(),
                           nb_trash=len(list_trash(current_app.bookdir.dirpath)),
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
                           # space taken by the copies, freed by trashing them
                           copies_size=sum(f.filesize for b in books for f in duplicates[b.sha1]),
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

    books = d.get_all_books()
    analysis = metadata.AnalysisState(current_app.metadata, book)
    suggestions = metadata.suggestions(analysis.entry, book, books)

    # Without POST data, the form shows the current values (0: no year),
    # and the suggestions in the empty fields: nothing is saved until the
    # user submits the form
    form = BookForm(data=metadata.prefill({
        "title": book.title,
        "subtitle": book.subtitle,
        "authors": list(book.authors),
        "tags": book.tags,
        "editor": book.editor,
        "year": book.year or None,
        "isbn": book.isbn,
    }, suggestions))
    if form.validate_on_submit():
        book.title = form.title.data
        book.subtitle = form.subtitle.data
        book.authors = form.authors.data or []
        book.tags = form.tags.data
        book.editor = form.editor.data
        book.year = form.year.data or 0
        book.isbn = form.isbn.data or ""
        if form.review.data:
            book.meta_reviewed = True
        elif form.unreview.data:
            book.meta_reviewed = False
        d.save_db()
        if d.read_only:
            flash("Base en lecture seule : modifications conservées en mémoire "
                  "seulement, elles seront perdues au redémarrage.", "error")
        elif form.review.data:
            flash("Modifications enregistrées, métadonnées marquées comme relues.")
        elif form.unreview.data:
            flash("Modifications enregistrées, métadonnées remises à relire.")
        else:
            flash("Modifications enregistrées.")
        return redirect(url_for(".bookadmin", sha1=sha1))
    if form.is_submitted():
        # the user input is shown: nothing is prefilled
        for s in suggestions.values():
            s.prefilled = False

    return render_template(
        "admin/book.html",
        book=book,
        form=form,
        suggestions=suggestions,
        analysis=analysis,
        # the book is analysed next, after the current one at most
        analysis_timeout=2 * TASK_TIMEOUT * 1000,
        analyse_form=AnalyseForm(prefix=ANALYSE_FORM_PREFIX),
        reset_form=_reset_form(),
        thumbnail=current_app.cache.thumbnail_info(book.sha1),
        # the indicators of the PDF file, when already measured (else
        # measured when their section is opened, see pdfstats_view())
        pdfstats=pdfstats.read(current_app.config["CACHE_DIR"], book.sha1),
        pdfstats_warnings=pdfstats.warnings,
        cover_form=CoverForm(prefix=COVER_FORM_PREFIX),
        # the original of the last transformation (cover page), in the trash
        original=d.original_in_trash(book.sha1),
        original_form=RestoreOriginalForm(prefix=ORIGINAL_FORM_PREFIX),
        cache_writable=current_app.cache.writable,
        rename_form=RenameBookForm(prefix=RENAME_FORM_PREFIX,
                                   data={"name": os.path.basename(book.filename)}),
        pattern_name=_pattern_name(book),
        move_form=_move_form(data={"category": _category_dir(book)}),
        trash_form=TrashBookForm(prefix=TRASH_FORM_PREFIX),
        library_tags=sorted({t for b in books for t in b.tags.split()}),
        library_editors=sorted({b.editor for b in books if b.editor}),
        copies=d.get_duplicates().get(book.sha1, []),
        titre=f"eBook admin - {os.path.basename(book.filename)}")


@admin.route("/bookadmin/<sha1>/analyse", methods=["POST"])
@login_required
def analyse(sha1):
    """ Analyse the PDF file of a book again, before the other books """
    book = _book_or_404(sha1)
    form = AnalyseForm(prefix=ANALYSE_FORM_PREFIX)
    if not form.validate_on_submit():
        flash(CSRF_ERROR, "error")
    elif not book.present:
        flash("Le PDF est absent du répertoire des livres : "
              "il ne peut pas être analysé.", "error")
    elif not current_app.metadata.running:
        flash("L'analyse des PDF est désactivée, ou le répertoire du cache "
              "n'est pas accessible en écriture.", "error")
    else:
        current_app.metadata.request(sha1, os.path.join(book.book_dir, book.filename),
                                     urgent=True, force=True)
        flash("Analyse demandée : les suggestions sont mises à jour dans quelques secondes.")
    return redirect(url_for(".bookadmin", sha1=sha1))


@admin.route("/bookadmin/<sha1>/analysis")
@login_required
def analysis_state(sha1):
    """ JSON: whether the analysis of a book is pending (book page) """
    _book_or_404(sha1)
    return jsonify(pending=current_app.metadata.is_pending(sha1))


@admin.route("/bookadmin/<sha1>/thumbnail")
@login_required
def thumbnail_state(sha1):
    """ JSON: whether the thumbnail of a book exists (book page, after a regeneration) """
    _book_or_404(sha1)
    return jsonify(ready=os.path.exists(current_app.cache.get_thumbname(sha1)))


@admin.route("/bookadmin/<sha1>/pdfstats")
@login_required
def pdfstats_view(sha1):
    """
    HTML fragment: the indicators of the PDF file of a book (section
    "Structure du PDF" of the book page), measured if needed (a few
    hundred ms), kept in the cache. ?force=1 measures again.
    """
    book = _book_or_404(sha1)
    stats = None
    if book.present:
        stats = pdfstats.get(current_app.config["CACHE_DIR"], sha1,
                             os.path.join(book.book_dir, book.filename),
                             writable=current_app.cache.writable,
                             force=request.args.get("force") == "1")
    return render_template("admin/_pdfstats.html", book=book, pdfstats=stats,
                           pdfstats_warnings=pdfstats.warnings)


def _reset_form():
    """ The form of the thumbnail regeneration, with the available backends """
    form = ResetThumbnailForm(prefix=RESET_FORM_PREFIX)
    form.backend.choices = [(b, THUMBNAIL_BACKEND_LABELS.get(b, b))
                            for b in [""] + available_backends()]
    return form


@admin.route("/reset-thumbnail/<sha1>", methods=["POST"])
@login_required
def reset_thumbnail(sha1):
    """ Delete the thumbnail of a book, and queue its regeneration """
    d = current_app.bookdir
    book = d.find_book_by_sha1(sha1)
    if book is None:
        abort(404)

    form = _reset_form()
    if not form.validate_on_submit():
        flash(form.backend.errors[0] if form.backend.errors else CSRF_ERROR, "error")
    elif not book.present:
        flash("Le PDF est absent du répertoire des livres : "
              "la miniature ne peut pas être régénérée.", "error")
    elif not current_app.cache.writable:
        flash("Le répertoire des miniatures n'est pas accessible en écriture : "
              "la miniature ne peut pas être régénérée.", "error")
    else:
        thumbname = current_app.cache.get_thumbname(sha1)
        try:
            os.remove(thumbname)
        except FileNotFoundError:
            pass
        backend = form.backend.data or None
        pdffile = os.path.join(book.book_dir, book.filename)
        current_app.logger.info("Regenerate thumbnail of '%s' (backend: %s)",
                                pdffile, backend or "any")
        current_app.cache.create_thumbnail(pdffile, sha1, backend)
        # No promise of a reload here: the thumbnail may be ready before
        # the book page is shown, which then waits for nothing
        flash(f"Miniature en cours de régénération ({THUMBNAIL_BACKEND_LABELS[form.backend.data]}).")

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
    if is_read_only():
        current_app.logger.warning("%s: %s refused: read-only mode", user, description)
        flash("Opération refusée : le site est en lecture seule, "
              "le répertoire des livres n'est pas modifié.", "error")
        return None
    try:
        result = operation()
    except BookFileError as e:
        current_app.logger.warning("%s: %s refused: %s", user, description, e)
        flash(f"Opération refusée : {e}", "error")
        return None
    current_app.logger.warning("%s: %s -> '%s'", user, description, result)
    return result


def _pattern_name(book):
    """
    {'pattern', 'name' or 'error', 'taken', 'conform'}: the name after
    FILENAME_PATTERN, with a suffix ' (2)', ... when another file of the
    directory has it ('taken': this name)
    """
    pattern = current_app.config["FILENAME_PATTERN"]
    current = os.path.basename(book.filename)
    try:
        wanted = naming.file_name(pattern, book)
        name = naming.free_name(os.path.join(current_app.bookdir.dirpath,
                                             os.path.dirname(book.filename)),
                                wanted, own=current)
    except naming.NamingError as e:
        return {"pattern": pattern, "name": None, "error": str(e), "taken": None,
                "conform": False}
    return {"pattern": pattern, "name": name, "error": None,
            "taken": wanted if name != wanted else None, "conform": name == current}


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


def _transformed(result):
    """
    A book whose file was replaced (transformation, restored original): its
    reading position follows it. Returns its page (new URL).
    """
    move_reader_state(result.old_sha1, result.new_sha1, result.page_offset)
    return redirect(url_for(".bookadmin", sha1=result.new_sha1))


@admin.route("/bookadmin/<sha1>/cover", methods=["POST"])
@login_required
def insert_cover(sha1):
    """ A cover page made of the uploaded image, in the PDF file; the original in the trash """
    book = _book_or_404(sha1)
    form = CoverForm(prefix=COVER_FORM_PREFIX)
    if not form.validate_on_submit():
        _flash_form_errors(form)
        return redirect(url_for(".bookadmin", sha1=sha1))

    image = form.image.data.read()
    result = _file_operation(f"insert a cover in '{book.filename}'",
                             lambda: current_app.bookdir.transform(sha1, CoverPage(image)))
    if not result:
        return redirect(url_for(".bookadmin", sha1=sha1))
    flash(f"Page de couverture insérée. L'original est dans la corbeille : {result.trashed}")
    return _transformed(result)


@admin.route("/bookadmin/<sha1>/original", methods=["POST"])
@login_required
def restore_original(sha1):
    """ Undo the last transformation of a book: its original back, the transformed file in the trash """
    book = _book_or_404(sha1)
    form = RestoreOriginalForm(prefix=ORIGINAL_FORM_PREFIX)
    if not form.validate_on_submit():
        flash(CSRF_ERROR, "error")
        return redirect(url_for(".bookadmin", sha1=sha1))
    result = _file_operation(f"restore the original of '{book.filename}'",
                             lambda: current_app.bookdir.restore_original(sha1))
    if not result:
        return redirect(url_for(".bookadmin", sha1=sha1))
    flash(f"Original restauré. Le fichier remplacé est dans la corbeille : {result.trashed}")
    return _transformed(result)


@admin.errorhandler(RequestEntityTooLarge)
def request_too_large(e):
    """ An upload over MAX_CONTENT_LENGTH: back to the page, with a message """
    flash(f"Fichier trop volumineux : {current_app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)} "
          "Mo au plus.", "error")
    sha1 = (request.view_args or {}).get("sha1")
    return redirect(url_for(".bookadmin", sha1=sha1) if sha1 else url_for(".book_list"))


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
    files = list_trash(current_app.bookdir.dirpath)
    return render_template("admin/trash.html",
                           files=files,
                           total_size=sum(f.filesize for f in files),
                           restore_form=RestoreForm(),
                           delete_form=DeleteFromTrashForm(),
                           empty_form=EmptyTrashForm(),
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


@admin.route("/bookadmin/trash/delete", methods=["POST"])
@login_required
def delete():
    form = DeleteFromTrashForm()
    if not form.validate_on_submit():
        _flash_form_errors(form)
    else:
        filename = form.filename.data
        deleted = _file_operation(
            f"delete '{filename}'",
            lambda: delete_from_trash(current_app.bookdir.dirpath, filename))
        if deleted:
            flash(f"Fichier supprimé définitivement : {deleted}")
    return redirect(url_for(".trash"))


@admin.route("/bookadmin/trash/empty", methods=["POST"])
@login_required
def empty():
    form = EmptyTrashForm()
    if not form.validate_on_submit():
        _flash_form_errors(form)
    else:
        count = _file_operation(
            "empty the trash",
            lambda: empty_trash(current_app.bookdir.dirpath))
        if count is not None:
            flash(f"Corbeille vidée : {count} fichier{'s' if count > 1 else ''} "
                  f"supprimé{'s' if count > 1 else ''} définitivement.")
    return redirect(url_for(".trash"))
