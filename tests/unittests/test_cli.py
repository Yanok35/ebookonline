""" Command line interface (app/cli.py): flask thumbnails ... """

from pathlib import Path

import pytest

from tests.conftest import make_pdf, write_jpeg

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
    return app.test_cli_runner().invoke(args=["thumbnails", *args])


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


def test_regenerate_for_real(app, books):
    """ The CMYK thumbnail is replaced by an RGB one """
    result = run(app, "regenerate", "--cmyk")
    if result.exit_code == 1:
        pytest.skip("ImageMagick refuses the PDF files (security policy)")
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
