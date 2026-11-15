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
Background processes which keep the metadata cache files of the books up to
date (srcs/metadata/store.py).

The server process keeps the queue of the books to process, in a
dispatcher thread, and feeds the worker processes through a bounded
multiprocessing queue: a request marked urgent (e.g. from the book page)
goes first, and waits for at most one task per worker. A worker only gets a
sha1 and a path, and writes the cache file of the book: it changes nothing
else, so that several workers can run (METADATA_WORKERS).

A worker which dies (e.g. a crash of MuPDF on a malformed file) is
restarted, and the book it was processing is saved as failed, so that it is
not tried again at each start.
"""

import atexit
import logging
import multiprocessing
import os
import queue
import signal
import threading
import time
from collections import OrderedDict

from srcs.logs import setup_logging
from srcs.metadata import store

log = logging.getLogger(__name__)

# Largest time to process a book, in seconds: a longer one is stopped, and
# saved as failed
TASK_TIMEOUT = 300

# A worker which dies without processing a book (e.g. at its start) is
# restarted after 1, 2, 4, ... seconds, MAX_RESTART_DELAY at most, instead
# of in a loop; a worker which dies on a book (e.g. a crash of MuPDF on a
# malformed file) is restarted at once.
MAX_RESTART_DELAY = 60


def default_workers():
    """ Number of workers for METADATA_WORKERS = 0: half of the processors """
    return max(1, (os.cpu_count() or 2) // 2)


class _Timeout(Exception):
    pass


def _alarm(signum, frame):
    raise _Timeout()


def analyse_book(cache_dir, sha1, pdf_path, force=False):
    """
    store.update() of a book, stopped after TASK_TIMEOUT seconds, an error
    saved in its cache file: never raises. Returns the status (store.*).
    In the main thread of a process only (SIGALRM): a worker process of the
    service, or the command line (app/cli.py).
    """
    previous = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(TASK_TIMEOUT)
    try:
        return store.update(cache_dir, sha1, pdf_path, force)
    except _Timeout:
        store.write_error(cache_dir, sha1, f"analysis stopped after {TASK_TIMEOUT} s")
        return store.FAILED
    except Exception as e:
        log.exception("Metadata of %s: analysis failed", pdf_path)
        store.write_error(cache_dir, sha1, f"{store.INTERNAL_ERROR}{type(e).__name__}: {e}")
        return store.FAILED
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _worker_main(num, cache_dir, tasks, results, log_level, nice):
    """ Loop of a worker process: (sha1, pdf path, force) tasks, None to stop """
    setup_logging(log_level)
    # Stopped by the server (see MetadataService.stop()), not by a Ctrl-C
    # of the terminal
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if nice:
        os.nice(nice)
    log.debug("Metadata process %d: started", num)
    # the server (not the parent of the process with forkserver)
    server = multiprocessing.parent_process()
    while True:
        if server is not None and not server.is_alive():
            log.info("Metadata process %d: parent process is gone, exit", num)
            return
        try:
            task = tasks.get(timeout=1)
        except queue.Empty:
            continue
        if task is None:
            return
        sha1, pdf_path, force = task
        results.put(("start", num, sha1))
        status = analyse_book(cache_dir, sha1, pdf_path, force)
        if status != store.CURRENT:
            log.info("Metadata of %s: %s", pdf_path, status)
        results.put(("done", num, sha1, status))


class MetadataService:

    def __init__(self, cache_dir, workers=1, nice=10, writable=True):
        """
        workers: number of worker processes, 0 for default_workers().
        writable: false when the cache directory can not be written, then
        nothing runs and the requests are ignored (the cache files are still
        read, see store.read()).
        """
        self.cache_dir = cache_dir
        workers = int(workers)
        self.nb_workers = default_workers() if workers == 0 else max(1, workers)
        self.nice = nice
        self.writable = writable

        self._cond = threading.Condition()
        # {sha1: (pdf path, force)}, first out first
        self._todo = OrderedDict()
        # sha1 sent to a worker, not done yet
        self._sent = set()
        # sha1 whose cache file is up to date (or failed)
        self._done = set()
        # {worker number: sha1 being processed}
        self._busy = {}
        self._running = False
        # {worker number: process}, None while waiting for its restart
        self._processes = {}
        # {worker number: (deaths without processing a book, restart time)}
        self._restarts = {}
        self._tasks = None
        self._results = None
        self._threads = []

    # --- requests (server threads) ---

    def request(self, sha1, pdf_path, urgent=False, force=False):
        """
        Ask for the cache file of a book to be made up to date, from its PDF
        file. Ignored when the book is known up to date (unless force), and
        when the service does not run.
        """
        if not self._running:
            return
        with self._cond:
            if force:
                self._done.discard(sha1)
            elif sha1 in self._done:
                return
            if sha1 in self._sent and not force:
                return
            previous = self._todo.get(sha1)
            self._todo[sha1] = (pdf_path, force or bool(previous and previous[1]))
            if urgent:
                self._todo.move_to_end(sha1, last=False)
            self._cond.notify_all()

    @property
    def running(self):
        return self._running

    def is_pending(self, sha1):
        """ True when a book is waiting for, or under, processing """
        with self._cond:
            return sha1 in self._todo or sha1 in self._sent

    def pending_count(self):
        with self._cond:
            return len(self._todo) + len(self._sent)

    def read(self, sha1):
        """ The cache file of a book, see store.read() """
        return store.read(self.cache_dir, sha1)

    # --- life cycle ---

    def start(self):
        if self._running or not self.writable:
            return
        # Not forked from the server, which has threads (a fork could copy
        # a lock held by another thread): a worker restarted while it runs
        # is safe. The default of Python 3.14 on Linux.
        ctx = multiprocessing.get_context("forkserver")
        # bounded: the urgent requests wait for at most one task per worker
        self._tasks = ctx.Queue(maxsize=self.nb_workers)
        self._results = ctx.Queue()
        self._ctx = ctx
        self._running = True
        for num in range(self.nb_workers):
            self._spawn(num)
        for target, name in ((self._dispatch, "metadata-dispatch"),
                             (self._collect, "metadata-collect")):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)
        # Before multiprocessing terminates its processes at exit (atexit
        # handlers run last registered first): they are not restarted
        atexit.register(self.stop)
        log.info("Metadata service: %d process(es)", self.nb_workers)

    def _spawn(self, num):
        p = self._ctx.Process(
            target=_worker_main,
            args=(num, self.cache_dir, self._tasks, self._results,
                  logging.getLogger().getEffectiveLevel(), self.nice),
            name=f"metadata-{num}",
            daemon=True,
        )
        p.start()
        self._processes[num] = p

    def stop(self, timeout=5):
        with self._cond:
            if not self._running:
                return
            self._running = False
            self._todo.clear()
            self._cond.notify_all()
        for t in self._threads:
            t.join(timeout)
        for _ in self._processes:
            try:
                self._tasks.put(None, timeout=1)
            except queue.Full:
                break
        for p in self._processes.values():
            if p is None:
                continue
            p.join(timeout)
            if p.is_alive():
                p.terminate()
                p.join(timeout)
        self._processes.clear()
        self._restarts.clear()
        self._threads.clear()
        atexit.unregister(self.stop)

    # --- threads ---

    def _dispatch(self):
        """ Feed the workers, first of _todo first """
        while True:
            with self._cond:
                while self._running and not self._todo:
                    self._cond.wait()
                if not self._running:
                    return
                sha1, (pdf_path, force) = self._todo.popitem(last=False)
                self._sent.add(sha1)
            while True:
                try:
                    # blocks while every worker has a task waiting
                    self._tasks.put((sha1, pdf_path, force), timeout=1)
                    break
                except queue.Full:
                    if not self._running:
                        return

    def _collect(self):
        """ Results of the workers, and restart of the dead ones """
        while self._running:
            try:
                msg = self._results.get(timeout=1)
            except queue.Empty:
                msg = None
            except (EOFError, OSError):
                return
            if msg is not None:
                self._handle(msg)
            self._check_workers()

    def _handle(self, msg):
        with self._cond:
            if msg[0] == "start":
                _, num, sha1 = msg
                self._busy[num] = sha1
                return
            _, num, sha1, status = msg
            self._busy.pop(num, None)
            # it works: a next death is restarted at once
            self._restarts.pop(num, None)
            self._sent.discard(sha1)
            # MISSING: moved meanwhile, requested again by the next scan
            if status != store.MISSING:
                self._done.add(sha1)

    def _check_workers(self):
        now = time.monotonic()
        for num, p in list(self._processes.items()):
            if not self._running:
                return
            if p is None:
                # waiting for its restart
                if now >= self._restarts[num][1] and not self._restart(num):
                    return
                continue
            if p.is_alive():
                continue
            with self._cond:
                sha1 = self._busy.pop(num, None)
                if sha1:
                    self._sent.discard(sha1)
                    self._done.add(sha1)
            if sha1:
                store.write_error(self.cache_dir, sha1,
                                  f"the PDF reader stopped (exit code {p.exitcode})")
                deaths, delay = 0, 0
            else:
                deaths = self._restarts.get(num, (0, 0))[0] + 1
                delay = min(MAX_RESTART_DELAY, 2 ** (deaths - 1))
            log.error("Metadata process %d died (exit code %s)%s, restarted%s", num,
                      p.exitcode, f" while processing {sha1}" if sha1 else "",
                      f" in {delay} s" if delay else "")
            self._restarts[num] = (deaths, now + delay)
            self._processes[num] = None
            if not delay and not self._restart(num):
                return

    def _restart(self, num):
        """ Start worker num again; False when the server is exiting """
        try:
            self._spawn(num)
        except (OSError, ValueError):
            # the server is exiting (queues closed)
            if self._running:
                log.exception("Metadata process %d can not be restarted", num)
            return False
        return True
