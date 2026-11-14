#!/usr/bin/env python
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
Logger class for gunicorn, given on its command line:

    gunicorn --logger-class srcs.gunicorn_logger.GunicornLogger ...

gunicorn logs from its master process, before the application is loaded
(startup, workers, signals, timeouts): its messages then go through the
handler of ebookonline (see srcs.logs), with the same format and the
journald priorities, from the gunicorn --log-level option. The messages of
the application follow the LOG_LEVEL setting (config.py).
"""

from gunicorn.glogging import Logger

from srcs.logs import setup_logging


class GunicornLogger(Logger):

    def setup(self, cfg):
        super().setup(cfg)
        # (replaced by the application in the workers, with LOG_LEVEL)
        setup_logging(self.loglevel)
        # gunicorn messages go to the root logger, without its own handler
        for handler in list(self.error_log.handlers):
            self.error_log.removeHandler(handler)
        self.error_log.propagate = True
