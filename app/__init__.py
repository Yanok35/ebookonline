# -*- coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4

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
    from main import main as main_blueprint
    app.register_blueprint(main_blueprint)

    return app
