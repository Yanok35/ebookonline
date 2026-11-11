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

from config import Config
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from srcs.cache import Cache
from srcs.book import BookDir

def create_app(config_name):
    # instance_relative_config: relative paths given to from_pyfile() are
    # resolved from app.instance_path (<project>/instance) and not from the
    # 'app' package directory.
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    # Local overrides, kept out of git (instance/ folder at project root)
    app.config.from_pyfile('config.py', silent=True)
    # Production: secrets come from the environment, e.g. EBOOKONLINE_SECRET_KEY
    app.config.from_prefixed_env(prefix='EBOOKONLINE')

    if not app.config.get('SECRET_KEY'):
        raise RuntimeError(
            "SECRET_KEY is not set: define EBOOKONLINE_SECRET_KEY or set it "
            f"in {os.path.join(app.instance_path, 'config.py')}"
        )

    if app.config['BEHIND_REVERSE_PROXY']:
        # Single reverse proxy to trust
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=1,
            x_proto=1,
            x_host=1
        )

    app.cache = Cache.get_instance(app.config['CACHE_DIR'])
    app.bookdir = BookDir(app.config['BOOK_DB'], app.cache)
    # initial scan of available books
    app.bookdir.scan_dir(app.config['BOOK_DIR'])

    # Blueprint registration
    from app.main import main as main_blueprint
    app.register_blueprint(main_blueprint)

    from .api import api as api_blueprint
    app.register_blueprint(api_blueprint)

    return app
