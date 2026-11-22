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

"""
Configuration of ebookonline, for the server (app/__init__.py) and the
command line (srcs/cli.py), from the weakest to the strongest:

1. config.py (project root), class Config: the documented defaults;
2. instance/config.py: the local settings (not in git), optional;
3. the environment variables EBOOKONLINE_<NAME>: a value is decoded as
   JSON when possible (numbers, booleans, {...}), a text otherwise;
   EBOOKONLINE_A__B sets the key B of the dictionary A.

Only the upper case names are settings. The relative paths (BOOK_DIR,
BOOK_DB, ...) are relative to the current directory. These are the rules
of Flask (Config.from_object(), from_pyfile(), from_prefixed_env()), kept
so that the server and the command line read the same settings.
"""

import json
import os
import types

PREFIX = "EBOOKONLINE_"

# The project: the directory of config.py (the defaults)
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTANCE_CONFIG = os.path.join(PROJECT_DIR, "instance", "config.py")


def _settings(obj):
    """ The upper case names of a class or a module, with their values """
    return {name: getattr(obj, name) for name in dir(obj) if name.isupper()}


def load(environ=None, instance_config=INSTANCE_CONFIG):
    """ The settings, as a dict: the defaults, the instance file, the environment """
    from config import Config

    settings = _settings(Config)
    if os.path.isfile(instance_config):
        module = types.ModuleType("config")
        module.__file__ = instance_config
        with open(instance_config, "rb") as f:
            exec(compile(f.read(), instance_config, "exec"), module.__dict__)
        settings.update(_settings(module))

    environ = os.environ if environ is None else environ
    for key in sorted(environ):
        if not key.startswith(PREFIX):
            continue
        value = environ[key]
        try:
            value = json.loads(value)
        except ValueError:
            # a text
            pass
        *parts, name = key[len(PREFIX):].split("__")
        current = settings
        for part in parts:
            current = current.setdefault(part, {})
        current[name] = value
    return settings
