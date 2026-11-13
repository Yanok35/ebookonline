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
from wtforms import HiddenField, IntegerField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional, Regexp, ValidationError

YEAR_MIN, YEAR_MAX = 1450, 2100


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


def _year_range(form, field):
    # not checked when the value could not be parsed (data is None)
    if field.data is not None and not YEAR_MIN <= field.data <= YEAR_MAX:
        raise ValidationError(f"Année entre {YEAR_MIN} et {YEAR_MAX}.")


class BookForm(FlaskForm):
    """ User-defined attributes of a book (admin page) """

    tags = StringField(
        "Tags",
        filters=[_normalize_tags],
        validators=[Length(max=500)],
        description="Séparés par des espaces.")
    editor = StringField(
        "Éditeur",
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


class ResetThumbnailForm(FlaskForm):
    """ Delete and regenerate the thumbnail of a book (CSRF protection only) """

    submit = SubmitField("Régénérer la miniature")


# File operations: the paths are checked by BookDir (srcs/bookfileops.py)

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


class TrashBookForm(FlaskForm):
    """ Move the file of a book to the trash (CSRF protection only) """

    submit = SubmitField("Mettre à la corbeille")


class TrashDuplicateForm(FlaskForm):
    """ Move a duplicate file to the trash """

    filename = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Corbeille")
