#!/usr/bin/env python
# -*- coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4

import os
import sys

from app import create_app
from flask.ext.script import Manager

from app.cache import Cache
from app.book import Book

basedir = os.path.abspath(os.path.dirname(__file__))

#
# Globals
#
app = create_app(os.getenv('FLASK_CONFIG') or 'default')
manager = Manager(app)

CFG_FILE = os.path.join(basedir, "ebookonline.conf")
if os.path.exists(CFG_FILE):
    print("Parsing conf file...")
    execfile(CFG_FILE)

    assert(SECRET_KEY)
    assert(len(creds.keys()))
    assert(BOOK_DIR)
    assert(CACHE_DIR)
    assert(BOOK_DB)
else:
    # Default values

    # You should generate a new one before hosting, using 'os.urandom(24)'
    SECRET_KEY = 'A0Zr98j/3yX R~XHH!jmN]LWX/,?RT'

    # user: password
    creds = {
        'yannick':  'test',
    }

    BOOK_DIR = os.path.abspath("books")
    CACHE_DIR = os.path.abspath("cache")
    BOOK_DB = "book.db"

app.secret_key = SECRET_KEY
#

#cache = Cache(CACHE_DIR)
cache = Cache.get_instance(CACHE_DIR)

print("set recursion limit from %d to 10000" % sys.getrecursionlimit())
sys.setrecursionlimit(10000)

# initial scan of available books
Book.scan_dir(BOOK_DB, BOOK_DIR)

if __name__ == '__main__':
    manager.run()
