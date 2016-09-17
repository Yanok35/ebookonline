# -*- coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4

from flask import Flask

def create_app(config_name):
    app = Flask(__name__)

    # Blueprint registration
    from main import main as main_blueprint
    app.register_blueprint(main_blueprint)

    return app
