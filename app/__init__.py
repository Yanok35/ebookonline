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

from config import Config
from flask import Flask

from app.cache import Cache
from app.book import BookDir

def create_app(config_name):
    app = Flask(__name__)
    app.config.from_object(Config)

    app.secret_key = app.config['SECRET_KEY']

    cache = Cache.get_instance(Config.CACHE_DIR)
    app.bookdir = BookDir(Config.BOOK_DB)
    # initial scan of available books
    app.bookdir.scan_dir(Config.BOOK_DIR)

    # Blueprint registration
    from app.main import main as main_blueprint
    app.register_blueprint(main_blueprint)

    return app
