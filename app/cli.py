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
Command line interface, for the administrator: flask commands, with the
configuration of the server (instance/config.py, EBOOKONLINE_* variables).

    flask --app ebookonline thumbnails check [--list]
    flask --app ebookonline thumbnails regenerate --cmyk [--jobs 2]

The commands do not start the services of the server (directory scan,
watcher, thumbnail and analysis processes): they can run while the server
runs. book.db is only read.
"""

import logging
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, as_completed

import click
from flask import current_app
from flask.cli import AppGroup

from srcs.cache import BACKENDS, Cache, available_backends
from srcs.logs import setup_logging

thumbnails = AppGroup("thumbnails", help="Thumbnails of the books, in the cache directory.")

# States of a thumbnail, for the selection of the books
STATES = ("ok", "missing", "unreadable", "cmyk")


def thumbnail_state(info):
    """ The state (STATES) of a thumbnail, from Cache.thumbnail_info() """
    if info is None:
        return "missing"
    if info["width"] is None:
        return "unreadable"
    if info["cmyk"]:
        return "cmyk"
    return "ok"


def _present_books():
    return sorted((b for b in current_app.bookdir.get_all_books() if b.present),
                  key=lambda b: b.filename)


@thumbnails.command("check")
@click.option("--list", "show", is_flag=True, help="List the books whose thumbnail is not ok.")
def check(show):
    """
    Count the thumbnails of the books by state: ok, missing, unreadable (not
    a JPEG image), cmyk (colours wrong in the browsers: made by an older
    version, to regenerate).
    """
    counts = dict.fromkeys(STATES, 0)
    for book in _present_books():
        state = thumbnail_state(current_app.cache.thumbnail_info(book.sha1))
        counts[state] += 1
        if show and state != "ok":
            click.echo(f"{state:10} {book.sha1}  {book.filename}")
    click.echo(", ".join(f"{state}: {n}" for state, n in counts.items()))


# --- regeneration, in parallel processes ---

_worker_cache = None


def _init_worker(cachedir, log_level):
    global _worker_cache
    setup_logging(log_level)
    _worker_cache = Cache(cachedir, workers=0)


def _make_thumbnail(pdffilename, sha1, backend):
    return _worker_cache.make_thumbnail(pdffilename, sha1, backend)


def _select(states, books_args):
    """ The present books to regenerate: by state of their thumbnail, or named """
    d = current_app.bookdir
    selected = {}
    for arg in books_args:
        book = d.find_book_by_sha1(arg) or d.find_book_by_filename(arg)
        if book is None or not book.present:
            raise click.BadParameter(f"no present book with this sha1 or path: {arg}",
                                     param_hint="BOOKS")
        selected[book.sha1] = book
    if states:
        for book in _present_books():
            if thumbnail_state(current_app.cache.thumbnail_info(book.sha1)) in states:
                selected.setdefault(book.sha1, book)
    return sorted(selected.values(), key=lambda b: b.filename)


@thumbnails.command("regenerate")
@click.option("--cmyk", is_flag=True, help="The thumbnails in CMYK (wrong colours).")
@click.option("--missing", is_flag=True, help="The missing thumbnails.")
@click.option("--unreadable", is_flag=True, help="The thumbnails which are not JPEG images.")
@click.option("--all", "all_", is_flag=True, help="All the thumbnails.")
@click.option("--backend", type=click.Choice(BACKENDS),
              help="Backend to use; default: each one in turn, until one succeeds.")
@click.option("--jobs", "-j", type=click.IntRange(min=1), default=1, show_default=True,
              help="Number of parallel processes.")
@click.option("--dry-run", "-n", is_flag=True, help="List the books, regenerate nothing.")
@click.option("--verbose", "-v", is_flag=True, help="Log each thumbnail.")
@click.argument("books", nargs=-1)
def regenerate(cmyk, missing, unreadable, all_, backend, jobs, dry_run, verbose, books):
    """
    Regenerate the thumbnails of books: the ones selected by the options,
    and the BOOKS given by sha1 or path (relative to the book directory).

    Each thumbnail is replaced once the new one is made: the server shows
    the old one until then, and keeps it when the new one can not be made.
    The command may run while the server runs, e.g. under 'nice'.
    """
    if all_:
        states = set(STATES)
    else:
        states = {s for s, on in (("cmyk", cmyk), ("missing", missing),
                                  ("unreadable", unreadable)) if on}
    if not states and not books:
        raise click.UsageError("nothing to regenerate: give --cmyk, --missing, --unreadable, "
                               "--all, or books")
    if backend and backend not in available_backends():
        raise click.UsageError(f"backend not available here: {backend}")
    cache = current_app.cache
    if not cache.writable:
        raise click.ClickException(f"the cache directory can not be written: {cache.cachedir}")

    selected = _select(states, books)
    if dry_run or not selected:
        for book in selected:
            click.echo(f"{book.sha1}  {book.filename}")
        click.echo(f"{len(selected)} thumbnail(s) to regenerate" + (" (dry run)" if dry_run else ""))
        return

    # the INFO messages of each thumbnail would hide the progress bar
    log_level = logging.getLogger().getEffectiveLevel() if verbose else logging.WARNING
    cache_logger = logging.getLogger("srcs.cache")
    previous_level = cache_logger.level
    cache_logger.setLevel(log_level)
    failed = []
    try:
        with click.progressbar(length=len(selected), label="Thumbnails",
                               item_show_func=lambda b: b.filename[-50:] if b else None) as bar:
            if jobs == 1:
                for book in selected:
                    pdffile = os.path.join(current_app.bookdir.dirpath, book.filename)
                    if not cache.make_thumbnail(pdffile, book.sha1, backend):
                        failed.append(book)
                    bar.update(1, book)
            else:
                with ProcessPoolExecutor(
                        max_workers=jobs, mp_context=multiprocessing.get_context("forkserver"),
                        initializer=_init_worker, initargs=(cache.cachedir, log_level)) as pool:
                    futures = {pool.submit(_make_thumbnail,
                                           os.path.join(current_app.bookdir.dirpath, b.filename),
                                           b.sha1, backend): b for b in selected}
                    for future in as_completed(futures):
                        book = futures[future]
                        if not future.result():
                            failed.append(book)
                        bar.update(1, book)
    finally:
        cache_logger.setLevel(previous_level)

    for book in sorted(failed, key=lambda b: b.filename):
        click.echo(f"failed     {book.sha1}  {book.filename}", err=True)
    click.echo(f"{len(selected) - len(failed)} thumbnail(s) regenerated, {len(failed)} failed")
    if failed:
        raise SystemExit(1)
