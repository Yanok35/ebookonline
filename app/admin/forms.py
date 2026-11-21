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

import re

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import (
    HiddenField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, Optional, Regexp, ValidationError

YEAR_MIN, YEAR_MAX = 1450, 2100
AUTHORS_MAX, AUTHOR_MAX_LENGTH = 20, 200


def _strip(value):
    return value.strip() if isinstance(value, str) else value


def _normalize_tags(value):
    """ '  python   algo ' -> 'python algo' (tags are separated by spaces) """
    return " ".join(value.split()) if isinstance(value, str) else value


def _normalize_isbn(value):
    """ '978-1-0981-1316-2' -> '9781098113162' """
    return re.sub(r"[\s-]", "", value).upper() if isinstance(value, str) else value


class YearField(IntegerField):
    def process_formdata(self, valuelist):
        try:
            super().process_formdata(valuelist)
        except ValueError:
            raise ValueError("Année invalide.") from None


class AuthorsField(TextAreaField):
    """ A list of names: one per line, or separated by ';' """

    def process_formdata(self, valuelist):
        if valuelist:
            names = (n.strip() for n in re.split(r"[\n;]", valuelist[0]))
            self.data = [" ".join(n.split()) for n in names if n]

    def _value(self):
        return "\n".join(self.data or [])


def _authors_check(form, field):
    if len(field.data or []) > AUTHORS_MAX:
        raise ValidationError(f"{AUTHORS_MAX} auteurs au plus.")
    if any(len(n) > AUTHOR_MAX_LENGTH for n in field.data or []):
        raise ValidationError(f"{AUTHOR_MAX_LENGTH} caractères au plus par auteur.")


def _year_range(form, field):
    # not checked when the value could not be parsed (data is None)
    if field.data is not None and not YEAR_MIN <= field.data <= YEAR_MAX:
        raise ValidationError(f"Année entre {YEAR_MIN} et {YEAR_MAX}.")


class BookForm(FlaskForm):
    """ User-defined attributes of a book (admin page) """

    title = StringField(
        "Titre",
        filters=[_strip],
        validators=[Length(max=500)])
    subtitle = StringField(
        "Sous-titre",
        filters=[_strip],
        validators=[Length(max=500)],
        description="Facultatif.")
    authors = AuthorsField(
        "Auteurs",
        default=list,
        validators=[_authors_check],
        description="Un par ligne (ou séparés par « ; »).",
        render_kw={"rows": 2})
    tags = StringField(
        "Tags",
        filters=[_normalize_tags],
        validators=[Length(max=500)],
        description="Séparés par des espaces.")
    editor = StringField(
        "Éditeur",
        description="Maison d'édition.",
        filters=[_strip],
        validators=[Length(max=200)])
    year = YearField(
        "Année",
        validators=[Optional(), _year_range])
    isbn = StringField(
        "ISBN",
        filters=[_normalize_isbn],
        validators=[
            Optional(),
            Regexp(r"^(\d{9}[\dX]|\d{13})$",
                   message="ISBN-10 ou ISBN-13 attendu (tirets et espaces acceptés)."),
        ])
    submit = SubmitField("Enregistrer")
    # meta_reviewed: the user has reviewed the metadata, or not anymore
    review = SubmitField("Enregistrer et marquer comme relu")
    unreview = SubmitField("Enregistrer et remettre à relire")


class AnalyseForm(FlaskForm):
    """ Analyse the PDF file again (CSRF protection only) """

    submit = SubmitField("Relancer l'analyse")


# Backends of the thumbnails (srcs.cache.BACKENDS), as shown to the user
THUMBNAIL_BACKEND_LABELS = {
    "": "Automatique (le premier qui réussit)",
    "pypdf-wand": "pypdf puis ImageMagick (wand)",
    "wand": "ImageMagick (wand) seul",
    "ghostscript": "Ghostscript",
}


class BackendField(SelectField):
    def pre_validate(self, form):
        try:
            super().pre_validate(form)
        except ValidationError:
            raise ValidationError("Méthode de génération indisponible.") from None


class ResetThumbnailForm(FlaskForm):
    """
    Delete and regenerate the thumbnail of a book, with a backend (choices
    set by the view: the available ones), or each of them in turn ('')
    """

    backend = BackendField("Méthode", default="")
    submit = SubmitField("Régénérer la miniature")


# File operations: the paths are checked by BookDir (srcs/bookfileops.py)

class CoverForm(FlaskForm):
    """ Insert a cover page, from an image, in the PDF file (its original in the trash) """

    image = FileField(
        "Image de couverture",
        validators=[FileRequired("Image attendue."),
                    FileAllowed(["jpg", "jpeg", "png"], "Image JPEG ou PNG attendue.")],
        render_kw={"accept": "image/jpeg,image/png"},
    )
    submit = SubmitField("Insérer une page de couverture")


class RenameBookForm(FlaskForm):
    """ Rename the file of a book, in its directory """

    name = StringField(
        "Nouveau nom",
        filters=[_strip],
        validators=[DataRequired(message="Nom de fichier attendu."), Length(max=255)],
        description="Dans le même répertoire ; « .pdf » est ajouté s'il manque.")
    submit = SubmitField("Renommer")


class CategoryField(SelectField):
    def pre_validate(self, form):
        try:
            super().pre_validate(form)
        except ValidationError:
            raise ValidationError("Catégorie inconnue.") from None


class MoveBookForm(FlaskForm):
    """ Move the file of a book to a category (choices set by the view) """

    category = CategoryField("Catégorie")
    submit = SubmitField("Déplacer")


class RestoreOriginalForm(FlaskForm):
    """ Undo the last transformation of a book: its original back (CSRF protection only) """

    submit = SubmitField("Restaurer l'original")


class TrashBookForm(FlaskForm):
    """ Move the file of a book to the trash (CSRF protection only) """

    submit = SubmitField("Mettre à la corbeille")


class TrashDuplicateForm(FlaskForm):
    """ Move a duplicate file to the trash """

    filename = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Corbeille")


class RestoreForm(FlaskForm):
    """ Restore a file of the trash """

    filename = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Restaurer")


class DeleteFromTrashForm(FlaskForm):
    """ Delete for good a file of the trash """

    filename = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Supprimer")


class EmptyTrashForm(FlaskForm):
    """ Delete for good all the files of the trash (CSRF protection only) """

    submit = SubmitField("Vider la corbeille")
