#!/usr/bin/env python
# -*- coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4

import os
import sys

from app import create_app
from config import Config
from flask_script import Manager

basedir = os.path.abspath(os.path.dirname(__file__))

print("set recursion limit from %d to 10000" % sys.getrecursionlimit())
sys.setrecursionlimit(10000)

#
# Globals
#
app = create_app(os.getenv('FLASK_CONFIG') or 'default')
manager = Manager(app)


if __name__ == '__main__':
    manager.run()
