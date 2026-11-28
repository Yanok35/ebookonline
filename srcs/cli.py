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
Command line interface, for the administrator, independent of the web
server (Flask), with its configuration (srcs/config.py: config.py,
instance/config.py, EBOOKONLINE_* variables):

    python -m srcs.cli help [COMMAND]
    python -m srcs.cli thumbnails check [--list]
    python -m srcs.cli thumbnails regenerate --cmyk [--jobs 2]
    python -m srcs.cli metadata scan [--jobs 2]
    python -m srcs.cli metadata show <sha1 or path>
    python -m srcs.cli metadata stats
    python -m srcs.cli pdf audit [--warnings]
    python -m srcs.cli pdf show <sha1 or path>

The commands start none of the services of the server (directory scan,
watcher, thumbnail and analysis processes): they can run while it runs.
book.db is only read (opened read-only).
"""

import inspect
import logging
import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

import click

from srcs import config as settings
from srcs.pdf.thumbnails import BACKENDS, Cache, available_backends
from srcs.common.logs import setup_logging


class Library:
    """
    The configuration and the services of the book directory, made when
    first used: a command which needs no book list reads no book.db (the
    tests give theirs)
    """

    def __init__(self, config=None, cache=None, bookdir=None):
        self._config = config
        self._cache = cache
        self._bookdir = bookdir

    @property
    def config(self):
        if self._config is None:
            self._config = settings.load()
        return self._config

    @property
    def cache(self):
        """ The thumbnail cache, without processes: thumbnails made in this one """
        from srcs.services import make_cache

        if self._cache is None:
            self._cache = make_cache(self.config, workers=0)
        return self._cache

    @property
    def bookdir(self):
        """ The book directory, its last known book list: book.db only read """
        from srcs.services import make_bookdir

        if self._bookdir is None:
            self._bookdir = make_bookdir(self.config, self.cache, read_only=True)
        return self._bookdir


def library():
    """ The Library of the command being run """
    return click.get_current_context().find_object(Library)


class WholeShortHelp:
    """
    A command whose list of commands (group help) shows the whole first
    paragraph of its help, wrapped: click keeps its first sentence only,
    cut with '...' to the width of the terminal.
    """

    def get_short_help_str(self, limit=45):
        if self.short_help or not self.help:
            return super().get_short_help_str(limit)
        return " ".join(inspect.cleandoc(self.help).split("\n\n")[0].split())


class Command(WholeShortHelp, click.Command):
    pass


class Group(WholeShortHelp, click.Group):
    """ A group of commands made of Command """
    command_class = Command


def add_help_command(group):
    """ A 'help [COMMAND]' command in a group: its help, or the one of COMMAND """

    @group.command("help")
    @click.argument("command", required=False)
    @click.pass_context
    def help_(ctx, command):
        """
        Show the help of the commands, or of COMMAND (as --help).
        """
        group_ctx = ctx.parent
        if command is None:
            click.echo(group_ctx.get_help())
            return
        cmd = group_ctx.command.get_command(group_ctx, command)
        if cmd is None:
            raise click.UsageError(f"no such command: {command} (commands: "
                                   + ", ".join(group_ctx.command.list_commands(group_ctx)) + ")")
        with click.Context(cmd, info_name=command, parent=group_ctx) as cmd_ctx:
            click.echo(cmd.get_help(cmd_ctx))

    return help_


thumbnails = Group("thumbnails", help="Thumbnails of the books, in the cache directory.")
add_help_command(thumbnails)

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
    return sorted((b for b in library().bookdir.get_all_books() if b.present),
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
        state = thumbnail_state(library().cache.thumbnail_info(book.sha1))
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
    d = library().bookdir
    selected = {}
    for arg in books_args:
        book = d.find_book_by_sha1(arg) or d.find_book_by_filename(arg)
        if book is None or not book.present:
            raise click.BadParameter(f"no present book with this sha1 or path: {arg}",
                                     param_hint="BOOKS")
        selected[book.sha1] = book
    if states:
        for book in _present_books():
            if thumbnail_state(library().cache.thumbnail_info(book.sha1)) in states:
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
    cache = library().cache
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
    cache_logger = logging.getLogger("srcs.pdf.thumbnails")
    previous_level = cache_logger.level
    cache_logger.setLevel(log_level)
    failed = []
    try:
        with click.progressbar(length=len(selected), label="Thumbnails",
                               item_show_func=lambda b: b.filename[-50:] if b else None) as bar:
            if jobs == 1:
                for book in selected:
                    pdffile = os.path.join(library().bookdir.dirpath, book.filename)
                    if not cache.make_thumbnail(pdffile, book.sha1, backend):
                        failed.append(book)
                    bar.update(1, book)
            else:
                with ProcessPoolExecutor(
                        max_workers=jobs, mp_context=multiprocessing.get_context("forkserver"),
                        initializer=_init_worker, initargs=(cache.cachedir, log_level)) as pool:
                    futures = {pool.submit(_make_thumbnail,
                                           os.path.join(library().bookdir.dirpath, b.filename),
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


# --- metadata ---

metadata = Group("metadata", help="Metadata analysis of the PDF files (cache directory).")
add_help_command(metadata)


def _find_book(arg):
    """
    The book (book.db, present or not) of a sha1 or of a path; or a PDF
    file of the book directory unknown to book.db (e.g. a copy of the
    library without book.db), as a book without user values
    """
    from srcs.library.book import Book
    from srcs.common.files import sha1_file

    d = library().bookdir
    book = d.find_book_by_sha1(arg) or d.find_book_by_filename(arg)
    if book is not None:
        return book
    path = os.path.join(d.dirpath, arg)
    if arg.lower().endswith(".pdf") and os.path.isfile(path):
        book = Book(d.dirpath)
        book.set_sha1(sha1_file(path))
        book.set_filename(arg)
        return book
    raise click.BadParameter(f"no book with this sha1 or path: {arg}", param_hint="BOOK")


def _init_metadata_worker(log_level, nice):
    setup_logging(log_level)
    if nice:
        os.nice(nice)


def _analyse(cache_dir, sha1, pdf_path, force):
    from srcs.metadata.service import analyse_book
    return analyse_book(cache_dir, sha1, pdf_path, force)


@metadata.command("scan")
@click.option("--force", is_flag=True, help="Read the PDF files again, even when up to date.")
@click.option("--jobs", "-j", type=click.IntRange(min=1), default=1, show_default=True,
              help="Number of parallel processes.")
@click.option("--nice", type=click.IntRange(0, 19), default=10, show_default=True,
              help="Priority of the analysis (nice level).")
@click.option("--dry-run", "-n", is_flag=True, help="List the files, analyse nothing.")
@click.option("--verbose", "-v", is_flag=True, help="Log each analysis.")
@click.argument("books", nargs=-1)
def scan(force, jobs, nice, dry_run, verbose, books):
    """
    Analyse the PDF files of the book directory whose analysis is missing
    or outdated (or all of them, --force), or the BOOKS given by sha1 or
    path.

    The files are listed from the book directory itself: a file known to
    book.db (same path and modification time) is not hashed again, the
    other ones are. So the initial analysis of a large library can be made
    on another computer, from a copy of the library (with or without
    book.db): then copy its CACHE_DIR/*.meta.json.gz files to the cache
    directory of the server (they are named after the content of the
    files, not their path).
    """
    from srcs.metadata import store

    cache_dir = library().config["CACHE_DIR"]
    if not library().cache.writable:
        raise click.ClickException(f"the cache directory can not be written: {cache_dir}")

    click.echo("Listing the PDF files (the new ones are hashed)...", err=True)
    files = {}
    for f in sorted(library().bookdir.pdf_files(), key=lambda f: f.filename):
        files.setdefault(f.sha1, f)  # one analysis per content
    if books:
        by_path = {f.filename: f for f in files.values()}
        selected = {}
        for arg in books:
            f = files.get(arg) or by_path.get(arg)
            if f is None:
                raise click.BadParameter(f"no PDF file with this sha1 or path: {arg}",
                                         param_hint="BOOKS")
            selected[f.sha1] = f
        files = selected
    todo = [f for f in sorted(files.values(), key=lambda f: f.filename)
            if force or not store.is_current(store.read(cache_dir, f.sha1))]

    if dry_run or not todo:
        for f in todo:
            click.echo(f"{f.sha1}  {f.filename}")
        click.echo(f"{len(todo)} of {len(files)} file(s) to analyse" + (" (dry run)" if dry_run else ""))
        return

    log_level = logging.getLogger().getEffectiveLevel() if verbose else logging.WARNING
    loggers = [logging.getLogger(name) for name in ("srcs.metadata", "srcs.library")]
    previous_levels = [lg.level for lg in loggers]
    for lg in loggers:
        lg.setLevel(log_level)
    counts = {}
    failed = []
    try:
        with click.progressbar(length=len(todo), label="Analysis",
                               item_show_func=lambda f: f.filename[-50:] if f else None) as bar:
            def done(f, status):
                counts[status] = counts.get(status, 0) + 1
                if status == store.FAILED:
                    failed.append(f)
                bar.update(1, f)

            if jobs == 1:
                if nice:
                    os.nice(nice)
                for f in todo:
                    done(f, _analyse(cache_dir, f.sha1,
                                     os.path.join(library().bookdir.dirpath, f.filename), force))
            else:
                with ProcessPoolExecutor(
                        max_workers=jobs, mp_context=multiprocessing.get_context("forkserver"),
                        initializer=_init_metadata_worker, initargs=(log_level, nice)) as pool:
                    futures = {pool.submit(_analyse, cache_dir, f.sha1,
                                           os.path.join(library().bookdir.dirpath, f.filename),
                                           force): f for f in todo}
                    for future in as_completed(futures):
                        done(futures[future], future.result())
    finally:
        for lg, level in zip(loggers, previous_levels):
            lg.setLevel(level)

    for f in sorted(failed, key=lambda f: f.filename):
        entry = store.read(cache_dir, f.sha1) or {}
        click.echo(f"failed     {f.sha1}  {f.filename}: {entry.get('error')}", err=True)
    click.echo(", ".join(f"{status}: {n}" for status, n in sorted(counts.items())))


def _book_values(book):
    from srcs.metadata import analyse
    return {f: getattr(book, f) for f in analyse.FIELDS}


def _text(field, value):
    """ A value for a terminal: the authors separated by '; ' """
    if value is None or value == "" or value == [] or value == 0:
        return "-"
    return "; ".join(value) if isinstance(value, list) else str(value)


@metadata.command("show")
@click.argument("book")
@click.option("--text", is_flag=True, help="Also show the text extracted from the key pages.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def show(book, text, as_json):
    """
    Show the analysis of a BOOK (sha1 or path): its values in book.db, the
    suggestions, and the candidates with their source and weight.

    The candidates are found again from the raw data of the cache file,
    with the rules of this version of the code: a change of the rules
    (srcs/metadata/) is seen at once, without analysing the file again.
    """
    import json

    from srcs.metadata import analyse, store

    book = _find_book(book)
    entry = store.read(library().config["CACHE_DIR"], book.sha1)
    raw = (entry or {}).get("raw") or {}
    candidates = analyse.candidates(raw) if raw else (entry or {}).get("candidates") or {}
    learned = analyse.Learned.from_books(library().bookdir.get_all_books())
    suggestions = analyse.suggest(candidates, book.filename, learned) if candidates else {}

    if as_json:
        out = {"sha1": book.sha1, "filename": book.filename, "present": book.present,
               "reviewed": book.meta_reviewed, "values": _book_values(book),
               "cache": None if entry is None else {
                   k: entry.get(k) for k in ("extract_version", "analyser_version",
                                             "extracted_at", "analysed_at", "error")},
               "suggestions": suggestions, "candidates": candidates}
        if text:
            out["texts"] = raw.get("texts") or {}
        click.echo(json.dumps(out, ensure_ascii=False, indent=2))
        return

    click.echo(f"{book.filename}{'' if book.present else ' (missing)'}")
    click.echo(f"sha1 {book.sha1}, {'reviewed' if book.meta_reviewed else 'not reviewed'}")
    if entry is None:
        click.echo("cache: not analysed")
    elif entry.get("error"):
        click.echo(f"cache: error: {entry['error']}")
    else:
        click.echo(f"cache: analysed {entry.get('analysed_at')} (extract v{entry.get('extract_version')}, "
                   f"analyser v{entry.get('analyser_version')}"
                   f"{'' if store.is_current(entry) else ', outdated'})")

    click.echo()
    click.echo(f"{'field':10} {'book.db':35} suggestion")
    for field in analyse.FIELDS:
        s = suggestions.get(field)
        suggestion = "-" if s is None else \
            f"{_text(field, s['value'])}  [{s['score']}: {', '.join(s['sources'])}]"
        click.echo(f"{field:10} {_text(field, getattr(book, field))[:35]:35} {suggestion}")
        for alternative in (s or {}).get("alternatives", []):
            click.echo(f"{'':10} {'':35}   or {_text(field, alternative)}")

    click.echo()
    click.echo("candidates (weight, source, value):")
    for field in analyse.FIELDS:
        cands = sorted(candidates.get(field, []), key=lambda c: -c[2])
        if not cands:
            continue
        click.echo(f"  {field}")
        for value, source, weight in cands:
            click.echo(f"    {weight:5.0f}  {source:18} {_text(field, value)}")

    if text:
        for page, txt in sorted((raw.get("texts") or {}).items(), key=lambda kv: int(kv[0])):
            if txt.strip():
                click.echo(f"\n--- page {int(page) + 1}\n{txt.strip()}")


@metadata.command("stats")
@click.option("--live", is_flag=True,
              help="Find the candidates again with the rules of this version (slower), "
                   "instead of the cached ones.")
def stats(live):
    """
    Statistics of the analysis of the present books: state of the cache
    files, and for each field, the books whose value is filled in book.db,
    the books with a suggestion, and on the reviewed books, how often the
    suggestion is the value of book.db (overall, and with a score of 80 or
    more): a measure of the rules, to tune them.

    The editor spellings learned from book.db include the reviewed books
    themselves: the agreement of the editor is a little optimistic.
    """
    from srcs.metadata import analyse, store

    cache_dir = library().config["CACHE_DIR"]
    all_books = library().bookdir.get_all_books()
    books = [b for b in all_books if b.present]
    learned = analyse.Learned.from_books(all_books)
    cache = {"current": 0, "outdated": 0, "failed": 0, "internal error": 0, "not analysed": 0}
    fields = {f: {"filled": 0, "suggested": 0, "compared": 0, "agree": 0,
                  "compared80": 0, "agree80": 0} for f in analyse.FIELDS}

    with click.progressbar(books, label="Books", file=sys.stderr) as bar:
        for book in bar:
            entry = store.read(cache_dir, book.sha1)
            if entry is None:
                cache["not analysed"] += 1
            elif store.is_internal_error(entry):
                cache["internal error"] += 1
            elif entry.get("error"):
                cache["failed"] += 1
            elif not store.is_current(entry):
                cache["outdated"] += 1
            else:
                cache["current"] += 1
            raw = (entry or {}).get("raw") or {}
            candidates = analyse.candidates(raw) if live and raw else (entry or {}).get("candidates") or {}
            suggestions = analyse.suggest(candidates, book.filename, learned) if candidates else {}
            for field, c in fields.items():
                value = getattr(book, field)
                s = suggestions.get(field)
                c["filled"] += bool(value)
                c["suggested"] += s is not None
                if book.meta_reviewed and value and s is not None:
                    agree = analyse.same_value(field, value, s["value"])
                    c["compared"] += 1
                    c["agree"] += agree
                    if s["score"] >= 80:
                        c["compared80"] += 1
                        c["agree80"] += agree

    def rate(agree, compared):
        return f"{agree}/{compared} ({100 * agree // compared}%)" if compared else "-"

    reviewed = sum(b.meta_reviewed for b in books)
    click.echo(f"books: {len(books)} present, {reviewed} reviewed")
    click.echo("cache: " + ", ".join(f"{state} {n}" for state, n in cache.items()))
    click.echo()
    click.echo(f"{'field':10} {'filled':>7} {'suggested':>10}   "
               f"{'reviewed: same value':24} {'score >= 80':18}")
    for field, c in fields.items():
        click.echo(f"{field:10} {c['filled']:7} {c['suggested']:10}   "
                   f"{rate(c['agree'], c['compared']):24} {rate(c['agree80'], c['compared80']):18}")


# --- PDF indicators (srcs/pdf/stats.py)

pdf = Group("pdf", help="Indicators of the PDF files: what makes a book slow to open in the reader.")
add_help_command(pdf)


def _measure(cache_dir, sha1, pdf_path, force):
    from srcs.pdf import stats as pdfstats
    return pdfstats.get(cache_dir, sha1, pdf_path, writable=True, force=force)


def _mib(n):
    return f"{n / 1024 / 1024:7.1f} MB"


@pdf.command("audit")
@click.option("--force", is_flag=True, help="Measure again, even the files already measured.")
@click.option("--jobs", "-j", type=click.IntRange(min=1), default=1, show_default=True,
              help="Number of parallel processes.")
@click.option("--limit", type=click.IntRange(min=0), default=20, show_default=True,
              help="Number of books listed, the slowest first (0: all of them).")
@click.option("--warnings", "only_warnings", is_flag=True, help="List only the books with warnings.")
@click.argument("books", nargs=-1)
def audit(force, jobs, limit, only_warnings, books):
    """
    Measure the PDF files of the book directory, or the BOOKS given by sha1
    or path, then list them by the resources their heaviest page declares
    (what the reader downloads before drawing it), with their warnings.

    The indicators are kept in the cache directory (<sha1>.pdfstats.json):
    a file already measured is not read again (unless --force). The same
    indicators are shown by the book page, section "Structure du PDF".
    """
    from srcs.pdf import stats as pdfstats

    cache_dir = library().config["CACHE_DIR"]
    if not library().cache.writable:
        raise click.ClickException(f"the cache directory can not be written: {cache_dir}")

    click.echo("Listing the PDF files (the new ones are hashed)...", err=True)
    files = {}
    for f in sorted(library().bookdir.pdf_files(), key=lambda f: f.filename):
        files.setdefault(f.sha1, f)  # one measure per content
    if books:
        by_path = {f.filename: f for f in files.values()}
        selected = {}
        for arg in books:
            f = files.get(arg) or by_path.get(arg)
            if f is None:
                raise click.BadParameter(f"no PDF file with this sha1 or path: {arg}",
                                         param_hint="BOOKS")
            selected[f.sha1] = f
        files = selected

    results = {}
    todo = []
    for sha1, f in files.items():
        entry = None if force else pdfstats.read(cache_dir, sha1)
        if entry is None:
            todo.append(f)
        else:
            results[sha1] = entry
    path = lambda f: os.path.join(library().bookdir.dirpath, f.filename)
    if todo:
        with click.progressbar(length=len(todo), label="Measure", file=sys.stderr,
                               item_show_func=lambda f: f.filename[-50:] if f else None) as bar:
            if jobs == 1:
                for f in todo:
                    results[f.sha1] = _measure(cache_dir, f.sha1, path(f), force)
                    bar.update(1, f)
            else:
                with ProcessPoolExecutor(
                        max_workers=jobs,
                        mp_context=multiprocessing.get_context("forkserver")) as pool:
                    futures = {pool.submit(_measure, cache_dir, f.sha1, path(f), force): f
                               for f in todo}
                    for future in as_completed(futures):
                        f = futures[future]
                        results[f.sha1] = future.result()
                        bar.update(1, f)

    rows = []
    errors = []
    for sha1, entry in results.items():
        f = files[sha1]
        if entry is None or entry.get("error"):
            errors.append((f, (entry or {}).get("error", "missing")))
            continue
        rows.append((entry["resources"]["max"], f, entry, pdfstats.warnings(entry)))
    rows.sort(key=lambda r: (-r[0], r[1].filename))
    with_warnings = [r for r in rows if r[3]]
    listed = with_warnings if only_warnings else rows
    if limit:
        listed = listed[:limit]
    if listed:
        click.echo(f"{'page':>10} {'images':>6} {'file':>10}  book")
    for page_bytes, f, entry, warns in listed:
        click.echo(f"{_mib(page_bytes)} {entry['resources']['max_images']:6} "
                   f"{_mib(entry['file']['size'])}  {f.filename}")
        for w in warns:
            click.echo(f"{'':30}! {w}")
    for f, error in sorted(errors, key=lambda e: e[0].filename):
        click.echo(f"error  {f.filename}: {error}", err=True)
    click.echo(f"{len(rows)} file(s) measured, {len(with_warnings)} with warnings, "
               f"{len(errors)} unreadable")


@pdf.command("show")
@click.argument("book")
@click.option("--force", is_flag=True, help="Measure again.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def pdf_show(book, force, as_json):
    """
    Show the indicators of the PDF file of a BOOK (sha1 or path), measured
    if needed, and their warnings.
    """
    import json

    from srcs.pdf import stats as pdfstats

    book = _find_book(book)
    pdf_path = os.path.join(library().bookdir.dirpath, book.filename)
    entry = pdfstats.get(library().config["CACHE_DIR"], book.sha1, pdf_path,
                         writable=library().cache.writable, force=force)
    if entry is None:
        raise click.ClickException(f"no PDF file: {book.filename}")
    if as_json:
        click.echo(json.dumps(dict(entry, warnings=pdfstats.warnings(entry)), indent=2,
                              ensure_ascii=False))
        return
    click.echo(book.filename)
    if entry.get("error"):
        raise click.ClickException(entry["error"])
    f, res, img, fonts = entry["file"], entry["resources"], entry["images"], entry["fonts"]
    click.echo(f"file      {f['size'] / 1024 / 1024:.1f} MB, {f['pages']} pages, {f['version']}, "
               f"producer {f['producer'] or f['creator'] or '-'}, "
               f"{'linearized' if f['linearized'] else 'not linearized'}, "
               f"{f['objects']} objects, {f['updates']} incremental update(s)")
    click.echo("weight    " + ", ".join(f"{k} {v / 1024 / 1024:.1f} MB" for k, v in entry["bytes"].items()))
    click.echo(f"resources heaviest page {res['max_page']}: {res['max'] / 1024 / 1024:.1f} MB, "
               f"{res['max_images']} images; median {res['median'] / 1024 / 1024:.2f} MB; "
               f"{res['pages_over']} page(s) over 10 MB")
    click.echo(f"images    {img['count']}, {img['bytes'] / 1024 / 1024:.1f} MB, largest "
               f"{img['max_pixels'] / 1e6:.1f} MP, CMYK {img['cmyk']}, JPEG 2000 {img['jpx']}, "
               f"soft masks {img['soft_masks']}")
    click.echo(f"fonts     {fonts['count']}, embedded {fonts['embedded']}, subsets {fonts['subsets']}, "
               f"Type 3 {fonts['type3']}")
    click.echo(f"content   median {entry['content']['median'] / 1024:.0f} KB, largest "
               f"{entry['content']['max'] / 1024:.0f} KB (page {entry['content']['max_page']})")
    for w in pdfstats.warnings(entry):
        click.echo(f"! {w}")


# --- the root group

@click.group(cls=Group, context_settings={"help_option_names": ["-h", "--help"]})
@click.pass_context
def cli(ctx):
    """
    Command line interface of ebookonline: thumbnails, metadata analysis,
    PDF indicators. Configuration: config.py, instance/config.py, the
    EBOOKONLINE_* variables (as the server).
    """
    if ctx.obj is None:
        ctx.obj = Library()
    setup_logging(ctx.obj.config["LOG_LEVEL"])


cli.add_command(thumbnails)
cli.add_command(metadata)
cli.add_command(pdf)
add_help_command(cli)


if __name__ == "__main__":
    cli(prog_name="python -m srcs.cli")
