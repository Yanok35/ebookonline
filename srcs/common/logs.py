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
Logging configuration: every message goes to stderr, through the standard
logging module (one logger per module, logging.getLogger(__name__)).

Under systemd, stderr is collected by journald, which adds the date, the
process id and the unit name: each line then starts with its syslog priority
('<4>' for a warning, see sd-daemon(3)), so that 'journalctl -p warning'
filters it. Elsewhere (terminal, tests), lines start with the date and the
level.
"""

import logging
import os
import sys

# Format outside of the journal
CONSOLE_FORMAT = "%(asctime)s %(levelname)s [%(processName)s] %(name)s: %(message)s"
# Under the journal: date and pid are added by journald
JOURNAL_FORMAT = "%(name)s: %(message)s"

# Noisy loggers of libraries, and their minimum level
LIBRARY_LEVELS = {
    # warnings on each malformed PDF file, while making its thumbnail
    "pypdf": logging.ERROR,
}


def syslog_priority(levelno):
    """ The syslog priority of a logging level """
    if levelno >= logging.CRITICAL:
        return 2
    if levelno >= logging.ERROR:
        return 3
    if levelno >= logging.WARNING:
        return 4
    if levelno >= logging.INFO:
        return 6
    return 7


class JournalFormatter(logging.Formatter):
    """
    '<priority>name: message'. Every line gets the prefix: journald splits
    a stream into one entry per line, the lines of a traceback would
    otherwise get the default priority.
    """

    def __init__(self):
        super().__init__(JOURNAL_FORMAT)

    def format(self, record):
        prefix = f"<{syslog_priority(record.levelno)}>"
        return "\n".join(prefix + line for line in super().format(record).splitlines())


def under_journal(stream=None):
    """
    True when stream (stderr by default) is connected to the journal:
    systemd sets JOURNAL_STREAM to '<device>:<inode>' of this connection.
    """
    journal_stream = os.environ.get("JOURNAL_STREAM")
    if not journal_stream:
        return False
    try:
        st = os.fstat((stream or sys.stderr).fileno())
        device, inode = journal_stream.split(":")
        return (st.st_dev, st.st_ino) == (int(device), int(inode))
    except (OSError, ValueError, AttributeError):
        return False


def make_formatter():
    if under_journal():
        return JournalFormatter()
    return logging.Formatter(CONSOLE_FORMAT)


class LogHandler(logging.StreamHandler):
    """ The handler of ebookonline, on stderr: replaced by a new setup """

    def __init__(self, stream=None):
        super().__init__(stream or sys.stderr)
        self.setFormatter(make_formatter())


def setup_logging(level="INFO"):
    """
    Log to stderr from level ('DEBUG', 'INFO', ... or a number). Can be
    called again, e.g. by each application created by the tests, or in a
    thumbnail process: the previous handler is replaced.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, LogHandler):
            root.removeHandler(handler)
    root.addHandler(LogHandler())
    root.setLevel(level.upper() if isinstance(level, str) else level)
    for name, minimum in LIBRARY_LEVELS.items():
        logging.getLogger(name).setLevel(minimum)

