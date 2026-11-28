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
Versioned JSON files (book.db, userdata.db): the content of a file holds
its schema "version", and "min_reader_version", the oldest version of the
code which can read it. A file of an older version is migrated; a newer
one is read only when this code can read it (never rewritten: the data it
does not know would be lost).
"""


def file_version(db, path, version, error):
    """
    The schema version of the content db of the file path, read by code of
    schema version: raises error when it is newer and this code can not
    read it (its min_reader_version is newer than version).
    """
    found = db.get("version", 0)
    if found > version:
        # missing: only its own version is known to read it
        min_reader = db.get("min_reader_version", found)
        if min_reader > version:
            raise error(
                f"{path}: schema version {found} can only be read by schema "
                f"version {min_reader} or newer, this is version {version}: "
                f"upgrade ebookonline")
    return found


def migrate(db, migrations):
    """
    The content db converted to version len(migrations): migrations[n]
    converts the content of version n to n + 1
    """
    for convert in migrations[db.get("version", 0):]:
        db = convert(db)
    db["version"] = len(migrations)
    return db
