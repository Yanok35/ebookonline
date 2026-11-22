""" Command line interface (srcs/cli.py): python -m srcs.cli thumbnails ... """

import shutil
from pathlib import Path

import pytest

from tests.conftest import invoke_cli, make_pdf, write_jpeg

# The header of a CMYK JPEG image (4 components): enough for jpeg_info()
CMYK_JPEG = b"\xff\xd8\xff\xc0\x00\x11\x08" + (450).to_bytes(2, "big") + (300).to_bytes(2, "big") + b"\x04"


@pytest.fixture
def books(app):
    """ ok.pdf, cmyk.pdf, missing.pdf, bad.pdf: their thumbnail in this state """
    root = Path(app.config["BOOK_DIR"])
    for name in ("ok", "cmyk", "missing", "bad"):
        make_pdf(root / f"{name}.pdf")
    app.bookdir.rescan()
    found = {Path(b.filename).stem: b for b in app.bookdir.get_all_books()}
    write_jpeg(Path(app.cache.get_thumbname(found["ok"].sha1)), 30, 40)
    Path(app.cache.get_thumbname(found["cmyk"].sha1)).write_bytes(CMYK_JPEG)
    Path(app.cache.get_thumbname(found["bad"].sha1)).write_bytes(b"not an image")
    return found


def run(app, *args):
    return invoke_cli(app, "thumbnails", *args)


def test_check(app, books):
    result = run(app, "check", "--list")
    assert result.exit_code == 0
    assert result.output.splitlines() == [
        f"unreadable {books['bad'].sha1}  bad.pdf",
        f"cmyk       {books['cmyk'].sha1}  cmyk.pdf",
        f"missing    {books['missing'].sha1}  missing.pdf",
        "ok: 1, missing: 1, unreadable: 1, cmyk: 1",
    ]


def test_regenerate_dry_run(app, books):
    result = run(app, "regenerate", "--cmyk", "--missing", "-n")
    assert result.exit_code == 0
    assert result.output.splitlines() == [
        f"{books['cmyk'].sha1}  cmyk.pdf",
        f"{books['missing'].sha1}  missing.pdf",
        "2 thumbnail(s) to regenerate (dry run)",
    ]
    assert Path(app.cache.get_thumbname(books["cmyk"].sha1)).read_bytes() == CMYK_JPEG
    # by sha1 or path
    result = run(app, "regenerate", "-n", "ok.pdf", books["bad"].sha1)
    assert "2 thumbnail(s) to regenerate" in result.output


def test_regenerate(app, books, monkeypatch):
    made = []

    def make_thumbnail(pdffilename, sha1, backend=None):
        made.append((Path(pdffilename).name, backend))
        return Path(pdffilename).name != "missing.pdf"

    monkeypatch.setattr(app.cache, "make_thumbnail", make_thumbnail)
    result = run(app, "regenerate", "--cmyk", "--missing", "--backend", "wand")
    assert made == [("cmyk.pdf", "wand"), ("missing.pdf", "wand")]
    # a failure: told, exit status 1
    assert result.exit_code == 1
    assert f"failed     {books['missing'].sha1}  missing.pdf" in result.output
    assert "1 thumbnail(s) regenerated, 1 failed" in result.output


def test_regenerate_for_real(app, books, tmp_path):
    """ The CMYK thumbnail is replaced by an RGB one """
    # Skipped only when no backend can read a PDF file here: not on a
    # failure of the code
    pdffile = str(Path(app.config["BOOK_DIR"]) / "ok.pdf")
    if not shutil.which("gs") and \
            not app.cache._Cache__pdf2jpeg_wand_only(pdffile, str(tmp_path / "probe.jpg")):
        pytest.skip("ImageMagick refuses the PDF files (security policy), no Ghostscript")
    result = run(app, "regenerate", "--cmyk")
    assert result.exit_code == 0, result.output
    info = app.cache.thumbnail_info(books["cmyk"].sha1)
    assert info["width"] == 300 and not info["cmyk"]


@pytest.mark.parametrize("args, message", [
    ([], "nothing to regenerate"),
    (["unknown.pdf"], "no present book"),
    (["--backend", "magic", "--all"], "Invalid value for '--backend'"),
])
def test_regenerate_usage_errors(app, books, args, message):
    result = run(app, "regenerate", *args)
    assert result.exit_code == 2 and message in result.output


def test_regenerate_with_an_unavailable_backend(app, books, monkeypatch):
    monkeypatch.setattr("srcs.cache.shutil.which", lambda name: None)
    result = run(app, "regenerate", "--all", "--backend", "ghostscript")
    assert result.exit_code == 2 and "backend not available here: ghostscript" in result.output


def test_regenerate_without_writable_cache(app, books):
    app.cache.writable = False
    result = run(app, "regenerate", "--all")
    assert result.exit_code == 1 and "can not be written" in result.output


def test_help(app):
    result = run(app, "help")
    assert result.exit_code == 0
    assert "check" in result.output and "regenerate" in result.output
    result = run(app, "help", "regenerate")
    assert result.exit_code == 0 and "--cmyk" in result.output and "--jobs" in result.output
    result = run(app, "help", "foo")
    assert result.exit_code == 2 and "no such command: foo" in result.output


def test_help_lists_the_whole_first_paragraph(app):
    """ not its first sentence only, cut with '...' (click) """
    output = " ".join(run(app, "help").output.split("Commands:")[1].split())
    assert "..." not in output
    assert "check Count the thumbnails of the books by state: ok, missing, unreadable " \
           "(not a JPEG image), cmyk (colours wrong in the browsers: made by an older " \
           "version, to regenerate). help" in output


# --- metadata ---

import json
import os

from srcs.metadata import store
from tests.conftest import make_book_pdf


def book_pdf(path, title, author):
    return make_book_pdf(path, [[(28, title), (14, author)], [(10, "Some text.")]],
                         metadata={"title": title, "author": author})


@pytest.fixture
def library(app):
    """ Two books in book.db, not analysed """
    root = Path(app.config["BOOK_DIR"])
    book_pdf(root / "a.pdf", "Python Algorithms", "Magnus Lie Hetland")
    book_pdf(root / "Science" / "b.pdf", "Les Misérables", "Victor Hugo")
    app.bookdir.rescan()
    return {Path(b.filename).name: b for b in app.bookdir.get_all_books()}


def metadata(app, *args):
    return invoke_cli(app, "metadata", *args)


def test_metadata_scan(app, library):
    cache_dir = app.config["CACHE_DIR"]
    result = metadata(app, "scan", "-n")
    assert result.exit_code == 0
    assert "2 of 2 file(s) to analyse (dry run)" in result.output
    assert store.read(cache_dir, library["a.pdf"].sha1) is None

    result = metadata(app, "scan", "--nice", "0")
    assert result.exit_code == 0 and "extracted: 2" in result.output
    assert store.is_current(store.read(cache_dir, library["a.pdf"].sha1))
    assert "0 of 2 file(s) to analyse" in metadata(app, "scan").output
    # again, a book given by path
    result = metadata(app, "scan", "--force", "--nice", "0", "Science/b.pdf")
    assert result.exit_code == 0 and "extracted: 1" in result.output


def test_metadata_scan_of_files_unknown_to_book_db(app, library):
    """ e.g. a copy of the library on another computer: the files are hashed """
    root = Path(app.config["BOOK_DIR"])
    book_pdf(root / "c.pdf", "Dune", "Frank Herbert")
    result = metadata(app, "scan", "-n")
    assert "3 of 3 file(s) to analyse" in result.output and "c.pdf" in result.output
    # book.db is only read
    assert app.bookdir.find_book_by_filename("c.pdf") is None


def test_metadata_scan_in_parallel(app, library):
    result = metadata(app, "scan", "--jobs", "2", "--nice", "0")
    assert result.exit_code == 0, result.output
    assert "extracted: 2" in result.output


def test_metadata_scan_errors(app, library):
    result = metadata(app, "scan", "unknown.pdf")
    assert result.exit_code == 2 and "no PDF file with this sha1 or path" in result.output
    app.cache.writable = False
    result = metadata(app, "scan")
    assert result.exit_code == 1 and "can not be written" in result.output


def test_metadata_scan_reports_unreadable_files(app, library):
    (Path(app.config["BOOK_DIR"]) / "bad.pdf").write_bytes(b"not a PDF file")
    result = metadata(app, "scan", "--nice", "0")
    assert result.exit_code == 0
    assert "failed: 1" in result.output and "bad.pdf: can not open the PDF file" in result.output


def test_metadata_show(app, library):
    metadata(app, "scan", "--nice", "0")
    book = library["a.pdf"]
    book.title, book.meta_reviewed = "Python Algorithms", True
    result = metadata(app, "show", "a.pdf")
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert lines[:2] == ["a.pdf", f"sha1 {book.sha1}, reviewed"]
    assert lines[2].startswith("cache: analysed ")
    title = next(line for line in lines if line.startswith("title "))
    assert title.split()[1:3] == ["Python", "Algorithms"] and "[" in title
    assert any("large-font" in line or "title-page" in line for line in lines)

    out = json.loads(metadata(app, "show", book.sha1, "--json", "--text").output)
    assert out["values"]["title"] == "Python Algorithms" and out["reviewed"] is True
    assert out["suggestions"]["authors"]["value"] == ["Magnus Lie Hetland"]
    assert "Some text." in "".join(out["texts"].values())


def test_metadata_show_of_a_file_unknown_to_book_db(app, library):
    book_pdf(Path(app.config["BOOK_DIR"]) / "c.pdf", "Dune", "Frank Herbert")
    result = metadata(app, "show", "c.pdf")
    assert result.exit_code == 0
    assert "cache: not analysed" in result.output and "not reviewed" in result.output
    result = metadata(app, "show", "unknown.pdf")
    assert result.exit_code == 2 and "no book with this sha1 or path" in result.output


def test_metadata_stats(app, library):
    metadata(app, "scan", "--nice", "0")
    a, b = library["a.pdf"], library["b.pdf"]
    a.title, a.meta_reviewed = "Python Algorithms", True
    b.title, b.meta_reviewed = "Another Title", True
    result = metadata(app, "stats")
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert "books: 2 present, 2 reviewed" in lines
    assert "cache: current 2, outdated 0, failed 0, internal error 0, not analysed 0" in lines
    title = next(line for line in lines if line.startswith("title "))
    assert title.split()[:4] == ["title", "2", "2", "1/2"]
    # the rules of this version
    assert metadata(app, "stats", "--live").output.splitlines()[-7:] == lines[-7:]


def test_metadata_help(app):
    result = metadata(app, "help", "scan")
    assert result.exit_code == 0 and "--jobs" in result.output and "--force" in result.output
