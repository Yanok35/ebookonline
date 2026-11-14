import re

import pytest
from pathlib import Path

from tests.conftest import make_pdf


def test_image_requires_login(app):
    assert app.test_client().get("/images/" + "0" * 40).status_code == 302


def test_missing_thumbnail(app, client):
    response = client.get("/images/" + "0" * 40)
    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.data[:8] == b"\x89PNG\r\n\x1a\n"
    assert response.data == (Path(app.static_folder) / "missing-thumbnail.png").read_bytes()
    # revalidated by the browser, until the thumbnail is generated
    assert "no-cache" in response.headers["Cache-Control"] and response.headers["ETag"]


def test_thumbnail(app, client):
    make_pdf(Path(app.config["BOOK_DIR"]) / "a.pdf")
    app.bookdir.rescan()
    sha1 = app.bookdir.find_book_by_filename("a.pdf").sha1
    Path(app.cache.get_thumbname(sha1)).write_bytes(b"\xff\xd8 jpeg")

    response = client.get(f"/images/{sha1}")
    assert response.mimetype == "image/jpeg" and response.data == b"\xff\xd8 jpeg"


@pytest.fixture
def book(app):
    make_pdf(Path(app.config["BOOK_DIR"]) / "Science" / "Élève O'Reilly.pdf")
    app.bookdir.rescan()
    return app.bookdir.find_book_by_filename("Science/Élève O'Reilly.pdf")


def test_book_pdf(app, client, book):
    response = client.get(f"/pdf/{book.sha1}")
    assert response.status_code == 200 and response.mimetype == "application/pdf"
    assert response.data == (Path(app.config["BOOK_DIR"]) / book.filename).read_bytes()
    assert response.headers["Accept-Ranges"] == "bytes"
    # shown by the browser, saved under its name
    disposition = response.headers["Content-Disposition"]
    assert disposition.startswith("inline;") and "filename*=UTF-8''%C3%89l%C3%A8ve" in disposition
    assert "Deprecation" not in response.headers

    # by chunks (pdf.js)
    response = client.get(f"/pdf/{book.sha1}", headers={"Range": "bytes=0-9"})
    assert response.status_code == 206 and response.data == b"%PDF-1.3\n%"[:10]


def test_book_reader(client, book):
    response = client.get(f"/reader/{book.sha1}")
    assert response.status_code == 200
    html = response.text
    assert f'const PDF_URL = "/pdf/{book.sha1}?v="' in html
    assert f'"{book.sha1}"' in html
    # the name in the page, not in its URLs
    assert "<title>Élève O&#39;Reilly.pdf</title>" in html
    assert "/readpdf/" not in html and "/pdfjsviewer/" not in html


def test_unknown_or_missing_book(app, client, book):
    for url in [f"/pdf/{'0' * 40}", f"/reader/{'0' * 40}", "/pdf/not-a-sha1"]:
        assert client.get(url).status_code == 404
    (Path(app.config["BOOK_DIR"]) / book.filename).unlink()
    app.bookdir.rescan()
    assert client.get(f"/pdf/{book.sha1}").status_code == 404
    assert client.get(f"/reader/{book.sha1}").status_code == 404


def test_pdf_routes_require_login(app, book):
    client = app.test_client()
    for url in [f"/pdf/{book.sha1}", f"/reader/{book.sha1}",
                "/readpdf/Science/a.pdf", f"/pdfjsviewer/{book.sha1}/Science/a.pdf"]:
        response = client.get(url)
        assert response.status_code == 302 and "/login" in response.location


def test_library_links_to_the_reader(client, book):
    html = client.get("/browser_subset?subset-id=0").text
    assert f'href="/reader/{book.sha1}"' in html
    assert "/pdfjsviewer/" not in html and "/readpdf/" not in html


def test_deprecated_routes(app, client, book, caplog):
    import logging

    caplog.set_level(logging.INFO)
    reader = client.get(f"/pdfjsviewer/{book.sha1}/Science/%C3%89l%C3%A8ve%20O'Reilly.pdf")
    pdf = client.get("/readpdf/Science/%C3%89l%C3%A8ve%20O'Reilly.pdf")
    assert reader.status_code == 200 and pdf.status_code == 200
    assert pdf.data == (Path(app.config["BOOK_DIR"]) / book.filename).read_bytes()
    # identified as deprecated (RFC 9745: date of the deprecation)
    for response in [reader, pdf]:
        assert re.fullmatch(r"@\d+", response.headers["Deprecation"])
    assert "Deprecated route /readpdf/Science/Élève O'Reilly.pdf, use the main.book_pdf endpoint" \
        in caplog.text
    from app.main import pdf_read, pdfjs_read
    assert (pdf_read.deprecated_by, pdfjs_read.deprecated_by) == ("main.book_pdf", "main.book_reader")


def test_deprecated_readpdf_stays_in_the_book_directory(app, client, book):
    # book.db is next to the book directory
    assert (Path(app.config["BOOK_DIR"]).parent / "book.db").exists()
    assert client.get("/readpdf/..%2Fbook.db").status_code == 404
    # (the double slash is redirected to a path in the book directory)
    assert client.get("/readpdf/%2Fetc%2Fpasswd", follow_redirects=True).status_code == 404


def test_book_reader_shows_the_name_above_the_status(client, book):
    html = client.get(f"/reader/{book.sha1}").text
    assert re.search(r'<div id="docText">\s*'
                     r'<span id="docName" title="Élève O&#39;Reilly.pdf">Élève O&#39;Reilly.pdf</span>\s*'
                     r'<span id="status">', html)
