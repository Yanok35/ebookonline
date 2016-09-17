# -*- coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4

from flask import Blueprint

main = Blueprint('main', __name__)

from . import views
