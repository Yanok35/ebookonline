#!/usr/bin/env python
# -*- coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4

import os
import sys

from app import create_app
from config import Config
from flask_script import Manager

from app.cache import Cache
from app.book import Book

basedir = os.path.abspath(os.path.dirname(__file__))

#
# Globals
#
app = create_app(os.getenv('FLASK_CONFIG') or 'default')
manager = Manager(app)

#cache = Cache(CACHE_DIR)
cache = Cache.get_instance(Config.CACHE_DIR)

print("set recursion limit from %d to 10000" % sys.getrecursionlimit())
sys.setrecursionlimit(10000)

# initial scan of available books
Book.scan_dir(Config.BOOK_DB, Config.BOOK_DIR)

if __name__ == '__main__':
    manager.run()
