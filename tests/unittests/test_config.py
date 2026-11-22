""" Configuration (srcs/config.py), shared by the server and the command line """

import os
import subprocess
import sys
from pathlib import Path

from srcs import config
from tests.conftest import make_pdf


def test_defaults_then_instance_file_then_environment(tmp_path):
    instance = tmp_path / "config.py"
    instance.write_text("LOG_LEVEL = 'DEBUG'\nREADER_THEME = 'light'\nlowercase = 1\n")
    settings = config.load({"EBOOKONLINE_READER_THEME": "dark", "OTHER": "x"}, str(instance))
    # the defaults (config.py)
    assert settings["UPLOAD_MAX_SIZE"] == 500 * 1024 * 1024
    # the instance file
    assert settings["LOG_LEVEL"] == "DEBUG" and "lowercase" not in settings
    # the environment, the strongest
    assert settings["READER_THEME"] == "dark" and "OTHER" not in settings


def test_without_instance_file(tmp_path):
    settings = config.load({}, str(tmp_path / "missing.py"))
    assert settings["SECRET_KEY"] is None


def test_environment_values(tmp_path):
    settings = config.load({
        "EBOOKONLINE_BOOK_DIR_WATCH": "false",
        "EBOOKONLINE_METADATA_WORKERS": "3",
        "EBOOKONLINE_CREDENTIALS": '{"alice": "hash"}',
        "EBOOKONLINE_BOOK_DIR": "/srv/books",
        "EBOOKONLINE_EXTRA__INNER": "1",
    }, str(tmp_path / "missing.py"))
    # decoded as JSON, a text otherwise
    assert settings["BOOK_DIR_WATCH"] is False and settings["METADATA_WORKERS"] == 3
    assert settings["CREDENTIALS"] == {"alice": "hash"} and settings["BOOK_DIR"] == "/srv/books"
    # A__B: the key B of the dictionary A
    assert settings["EXTRA"] == {"INNER": 1}


def test_as_flask_reads_it(monkeypatch):
    """ the rules of Flask (from_object, from_pyfile, from_prefixed_env) """
    from flask import Flask
    from config import Config

    monkeypatch.setenv("EBOOKONLINE_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("EBOOKONLINE_X__Y", "[1, 2]")
    flask_app = Flask("app", root_path=os.path.join(config.PROJECT_DIR, "app"),
                      instance_relative_config=True)
    flask_app.config.from_object(Config)
    flask_app.config.from_pyfile("config.py", silent=True)
    flask_app.config.from_prefixed_env(prefix="EBOOKONLINE")
    settings = config.load()
    assert {k: flask_app.config[k] for k in settings} == settings


def test_command_line_without_flask_nor_secret_key(tmp_bookdir, library):
    """ python -m srcs.cli: the configuration of the environment, no SECRET_KEY needed """
    tmp_path, bookdir, cachedir = tmp_bookdir
    make_pdf(bookdir / "a.pdf")
    library.rescan()
    db = tmp_path / "book.db"
    saved = db.read_bytes()
    env = {k: v for k, v in os.environ.items() if not k.startswith("EBOOKONLINE_")}
    env.update({
        "EBOOKONLINE_SECRET_KEY": "", "EBOOKONLINE_CREDENTIALS": "{}",
        "EBOOKONLINE_BOOK_DIR": str(bookdir), "EBOOKONLINE_BOOK_DB": str(tmp_path / "book.db"),
        "EBOOKONLINE_CACHE_DIR": str(cachedir),
    })
    code = ("import runpy, sys; sys.argv = ['srcs.cli', 'thumbnails', 'check']; "
            "runpy.run_module('srcs.cli', run_name='__main__')\n"
            "assert 'flask' not in sys.modules, 'flask imported'")
    result = subprocess.run([sys.executable, "-c", code], cwd=config.PROJECT_DIR, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "ok: 0, missing: 1, unreadable: 0, cmyk: 0"
    # book.db only read
    assert db.read_bytes() == saved
