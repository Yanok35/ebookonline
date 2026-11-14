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


def test_readpdf_stays_in_the_book_directory(app, client):
    app.bookdir.rescan()
    # book.db is next to the book directory
    assert (Path(app.config["BOOK_DIR"]).parent / "book.db").exists()
    assert client.get("/readpdf/..%2Fbook.db").status_code == 404
