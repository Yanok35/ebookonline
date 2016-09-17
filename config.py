# -*- coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4
from __future__ import unicode_literals

import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    # You should generate a new one before hosting, using 'os.urandom(24)'
    SECRET_KEY = 'A0Zr98j/3yX R~XHH!jmN]LWX/,?RT'

    CREDENTIALS = {
        'yannick':  'test',
    }

    BOOK_DIR = os.path.join(basedir, "books")
    CACHE_DIR = os.path.join(basedir, "cache")
    BOOK_DB = "book.db"

