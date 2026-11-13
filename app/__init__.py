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

import click
from config import Config
from flask import Flask
from flask.helpers import get_debug_flag
from werkzeug.middleware.proxy_fix import ProxyFix

from srcs.cache import Cache
from srcs.book import BookDir
from srcs.watcher import BookDirWatcher

def _serves_requests():
    """
    False when the application is loaded by a process which will never serve
    requests, where the directory scan and watcher must not run:

    - the 'flask run --reload' (or --debug) watching process: Flask also loads
      the application there, before spawning the serving child process. Two
      scans and watchers in two processes would both rewrite book.db, each
      one with its own in-memory state, and generate the same thumbnails;
    - other flask commands (flask shell, flask routes, ...).

    gunicorn, app.run() and 'flask run' without reloader serve requests.
    """
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        # child process spawned by the reloader: it serves requests
        return True

    ctx = click.get_current_context(silent=True)
    if ctx is None:
        # not started by the flask command (gunicorn, app.run(), ...)
        return True
    if ctx.command.name != "run":
        return False

    # Same rule as 'flask run': the reloader is enabled by --reload, or by
    # default in debug mode.
    reload = ctx.params.get("reload")
    if reload is None:
        reload = get_debug_flag()
    return not reload

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
    # Last known book list, available at once (no directory scan)
    app.bookdir.open(app.config['BOOK_DIR'])

    # Startup scan: refresh book.db and the thumbnail cache, then keep them
    # up to date by watching the book directory.
    if _serves_requests():
        app.bookdir.scan_dir(app.config['BOOK_DIR'])
        if app.config['BOOK_DIR_WATCH']:
            app.bookdir_watcher = BookDirWatcher(
                app.bookdir, delay=app.config['BOOK_DIR_WATCH_DELAY'])
            app.bookdir_watcher.start()

    # Blueprint registration
    from app.main import main as main_blueprint
    app.register_blueprint(main_blueprint)

    from app.admin import admin as admin_blueprint
    app.register_blueprint(admin_blueprint)

    from .api import api as api_blueprint
    app.register_blueprint(api_blueprint)

    return app
