#!/usr/bin/env python
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
import sys

from app import create_app

basedir = os.path.abspath(os.path.dirname(__file__))

sys.setrecursionlimit(10000)

#
# Globals
#
# The application is created on first access to 'ebookonline.app' (PEP 562
# module __getattr__), not at import: 'gunicorn ebookonline:create_app(...)'
# imports this module then calls the factory, and an application created at
# import would be a second one, with its own directory scan and watcher.
# 'flask --app ebookonline' and 'gunicorn ebookonline:app' still work.
_app = None

def __getattr__(name):
    global _app
    if name in ("app", "application"):
        if _app is None:
            _app = create_app(os.getenv('FLASK_CONFIG') or 'default')
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

if __name__ == '__main__':
    create_app(os.getenv('FLASK_CONFIG') or 'default').run()
