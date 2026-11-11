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

from functools import wraps

from flask import jsonify, redirect, session, url_for


def is_logged_in():
    return 'username' in session


def login_required(view):
    """
    Decorator for HTML views: redirect anonymous users to the login page.
    """

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_logged_in():
            return redirect(url_for("main.login"))
        return view(*args, **kwargs)

    return wrapped


def api_login_required(view):
    """
    Decorator for JSON API endpoints: answer 401 instead of redirecting,
    so that javascript clients get a meaningful error.
    """

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_logged_in():
            return jsonify({"error": "Authentification requise."}), 401
        return view(*args, **kwargs)

    return wrapped
