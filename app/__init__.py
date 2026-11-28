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
import re

import click
from flask import Flask, current_app, request, session
from flask.helpers import get_debug_flag
from werkzeug.middleware.proxy_fix import ProxyFix

from srcs import config
from srcs.common.access import check_write_access
from srcs.common.logs import setup_logging
from srcs.book import DB_VERSION
from srcs.metadata.service import MetadataService
from srcs.services import make_bookdir, make_cache
from srcs.users.userdata import USERDATA_VERSION, UserData
from srcs.library.naming import NamingError, check_pattern
from srcs.library.watcher import BookDirWatcher

def _serves_requests():
    """
    False when the application is loaded by a process which will never serve
    requests, where the directory scan and watcher must not run:

    - the 'flask run --reload' (or --debug) watching process: Flask also loads
      the application there, before spawning the serving child process. Two
      scans and watchers in two processes would both rewrite book.db, each
      one with its own in-memory state, and generate the same thumbnails;
    - the other flask commands (flask shell, flask routes, ...).

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

def is_read_only():
    """
    True when the server writes nothing on the disk (book.db, reader states,
    files of the book directory): changes are kept in memory only, and lost
    at the next restart.
    """
    return bool(current_app.read_only_reasons)

def _read_only_context():
    """ For the read-only notices of the pages """
    return {
        "read_only": bool(current_app.read_only_reasons),
        "read_only_reasons": current_app.read_only_reasons,
    }

def _log_not_found(e):
    """
    For fail2ban: an anonymous client asking for a page which does not exist
    (typically a scan for vulnerable software) is logged as a warning, the
    address first (the path is chosen by the client). A logged in user (e.g.
    a stale link) is only logged as info, with another message.
    """
    user = session.get("username")
    if user is None:
        current_app.logger.warning("Not found from %s: %s %r",
                                   request.remote_addr, request.method, request.path)
    else:
        current_app.logger.info("Not found from %s for user %r: %s %r", request.remote_addr,
                                user, request.method, request.path)
    return e

def create_app():
    app = Flask(__name__)
    # config.py, instance/config.py, then the EBOOKONLINE_* variables (e.g.
    # the secrets in production): srcs/config.py, shared with the command
    # line
    app.config.update(config.load())

    # Before anything logs (Flask then adds no handler of its own)
    setup_logging(app.config['LOG_LEVEL'])

    if not app.config.get('SECRET_KEY'):
        raise RuntimeError(
            "SECRET_KEY is not set: define EBOOKONLINE_SECRET_KEY or set it "
            f"in {config.INSTANCE_CONFIG}"
        )

    # The logins key the data of the users (userdata.db, journal of the
    # reader events): letters, digits, '.', '_', '@', '-'
    for login in app.config['CREDENTIALS']:
        if not re.fullmatch(r"[\w.@-]+", login):
            raise RuntimeError(f"CREDENTIALS: invalid login {login!r} (letters, digits, "
                               "'.', '_', '@', '-')")

    try:
        check_pattern(app.config['FILENAME_PATTERN'])
    except NamingError as e:
        raise RuntimeError(f"FILENAME_PATTERN: {e}") from None

    if app.config['BEHIND_REVERSE_PROXY']:
        # Single reverse proxy to trust
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=1,
            x_proto=1,
            x_host=1
        )

    # No thumbnail processes in a process which serves no requests (the
    # watching process of the reloader, flask shell, ...)
    app.cache = make_cache(app.config, workers=None if _serves_requests() else 0)

    # Read-only when the server can not write where it needs to, or when
    # book.db was written by a newer version: the reasons, as messages.
    app.read_only_reasons = check_write_access(
        app.config['BOOK_DIR'], app.config['BOOK_DB'], app.config['STATE_FILE'],
        app.config['CACHE_DIR'], app.config['USERDATA_DB'])
    # Last known book list, available at once (no directory scan)
    app.bookdir = make_bookdir(app.config, app.cache, read_only=bool(app.read_only_reasons))
    # Suggestions of metadata, kept in the cache directory like the
    # thumbnails (also written in read-only mode, when writable)
    app.metadata = MetadataService(
        app.config['CACHE_DIR'], workers=app.config['METADATA_WORKERS'],
        nice=app.config['METADATA_NICE'], writable=app.cache.writable)
    app.bookdir.metadata = app.metadata
    if app.bookdir.db_version is not None:
        app.read_only_reasons.append(
            f"La base des livres a été écrite par une version plus récente "
            f"d'ebookonline (schéma {app.bookdir.db_version}, ce serveur gère "
            f"le schéma {DB_VERSION})")
    # The data of the users (notes): in memory only in read-only mode, as
    # the reading positions
    app.userdata = UserData(app.config['USERDATA_DB'], read_only=bool(app.read_only_reasons))
    if app.userdata.newer_version is not None:
        app.read_only_reasons.append(
            f"Les données des utilisateurs ont été écrites par une version plus "
            f"récente d'ebookonline (schéma {app.userdata.newer_version}, ce "
            f"serveur gère le schéma {USERDATA_VERSION})")
    # The reading positions and pins, common to all the users before: a
    # copy for each user, once
    from .api import import_common_data
    import_common_data(app)
    for reason in app.read_only_reasons:
        app.logger.warning("Read-only mode: %s", reason)
    app.context_processor(_read_only_context)

    # Startup scan: refresh book.db and the thumbnail cache, then keep them
    # up to date by watching the book directory.
    # The scan also asks for the analysis of the books (metadata).
    if _serves_requests():
        if app.config['METADATA_ANALYSIS']:
            app.metadata.start()
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

    from .timeline import timeline as timeline_blueprint
    app.register_blueprint(timeline_blueprint)

    app.register_error_handler(404, _log_not_found)

    return app
