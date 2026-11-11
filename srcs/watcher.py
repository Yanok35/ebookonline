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
Watch the book directory (inotify on Linux, through watchdog) and keep the
book database up to date while the server is running.

Events are not handled one by one: a copy in progress, an rsync writing a
temporary file then renaming it, or a whole directory being moved generate
bursts of events. They are debounced: once no relevant event has been
received for 'delay' seconds, a single incremental rescan of the directory
is run (BookDir.rescan, which only hashes new or modified files).
"""

import os
import threading

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

IGNORE_DIR_MARKER = ".ebook-ignore-dir"

# Event types that may change the book list. 'opened', 'closed_no_write'
# (a PDF being read) are not part of them.
RELEVANT_EVENT_TYPES = {"created", "deleted", "moved", "modified", "closed"}


def is_relevant(event):
    if event.event_type not in RELEVANT_EVENT_TYPES:
        return False

    if event.is_directory:
        # A directory 'modified' event only means that its content changed:
        # the matching file events are handled on their own.
        return event.event_type != "modified"

    paths = [event.src_path, getattr(event, "dest_path", "")]
    for path in paths:
        path = os.fsdecode(path)
        if path.lower().endswith(".pdf"):
            return True
        if os.path.basename(path) == IGNORE_DIR_MARKER:
            return True
    return False


class BookDirWatcher(FileSystemEventHandler):

    def __init__(self, bookdir, delay=2.0):
        super().__init__()
        self.bookdir = bookdir
        self.delay = delay
        self._timer = None
        self._timer_lock = threading.Lock()
        self._observer = None

    def start(self):
        self._observer = Observer()
        self._observer.daemon = True
        self._observer.schedule(self, self.bookdir.dirpath, recursive=True)
        self._observer.start()
        print("Watching %s for changes (delay %.1fs)"
              % (self.bookdir.dirpath, self.delay))

    def stop(self):
        with self._timer_lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None

    def on_any_event(self, event):
        if not is_relevant(event):
            return

        # (Re)start the countdown: the rescan happens once the directory
        # has been quiet for 'delay' seconds.
        with self._timer_lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.delay, self._rescan)
            self._timer.daemon = True
            self._timer.start()

    def _rescan(self):
        with self._timer_lock:
            # A newer timer may have been started meanwhile: keep track of it
            if self._timer is threading.current_thread():
                self._timer = None
        try:
            self.bookdir.rescan()
        except Exception as e:
            # Never let an error kill the watcher: next event will retry
            print("*** Error: book directory rescan failed: %r" % e)
