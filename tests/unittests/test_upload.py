""" Books uploaded from the library page: BookDir.add_book(), POST /upload """

import io
import re
from pathlib import Path

import pytest

from srcs.bookfileops import BookFileError
from tests.conftest import make_pdf


def pdf_bytes(tmp_path, title):
    return make_pdf(tmp_path / "src" / f"{title}.pdf", title=title).read_bytes()


# --- BookDir.add_book

def test_add_book(app, tmp_path):
    data = pdf_bytes(tmp_path, "Dune")
    relpath = app.bookdir.add_book(io.BytesIO(data), "Dune.pdf")
    assert relpath == "Incoming/Dune.pdf"
    assert (Path(app.config["BOOK_DIR"]) / relpath).read_bytes() == data
    # in the list at once
    book = app.bookdir.find_book_by_filename(relpath)
    assert book.present and book.category == "Incoming"
    # no temporary file left
    assert [p.name for p in (Path(app.config["BOOK_DIR"]) / "Incoming").iterdir()] == ["Dune.pdf"]
    assert (Path(app.config["BOOK_DIR"]) / relpath).stat().st_mode & 0o777 == 0o644


def test_add_book_keeps_an_existing_file(app, tmp_path):
    app.bookdir.add_book(io.BytesIO(pdf_bytes(tmp_path, "a")), "Dune.pdf")
    relpath = app.bookdir.add_book(io.BytesIO(pdf_bytes(tmp_path, "b")), "Dune.pdf")
    assert relpath == "Incoming/Dune (2).pdf"


@pytest.mark.parametrize("filename, expected", [
    ("C:\\Users\\me\\Dune.pdf", "Incoming/Dune.pdf"),      # a path of the client
    ("../../etc/Dune.pdf", "Incoming/Dune.pdf"),
    (".hidden.pdf", "Incoming/hidden.pdf"),
    ("  Élève O'Reilly.PDF ", "Incoming/Élève O'Reilly.PDF"),
])
def test_add_book_name(app, tmp_path, filename, expected):
    assert app.bookdir.add_book(io.BytesIO(pdf_bytes(tmp_path, "x")), filename) == expected


@pytest.mark.parametrize("data, filename, message", [
    (b"not a PDF file", "a.pdf", "not a PDF file"),
    (None, "notes.txt", "not a PDF file name"),
    (None, "", "not a PDF file name|invalid path"),
])
def test_add_book_refused(app, tmp_path, data, filename, message):
    data = data if data is not None else pdf_bytes(tmp_path, "x")
    with pytest.raises(BookFileError, match=message):
        app.bookdir.add_book(io.BytesIO(data), filename)
    incoming = Path(app.config["BOOK_DIR"]) / "Incoming"
    assert not incoming.exists() or list(incoming.iterdir()) == []


def test_add_book_header_after_garbage(app, tmp_path):
    """ the readers accept a header in the first 1024 bytes """
    data = b"\xef\xbb\xbf\n" + pdf_bytes(tmp_path, "x")
    assert app.bookdir.add_book(io.BytesIO(data), "x.pdf") == "Incoming/x.pdf"


# --- POST /upload

def token(client):
    html = client.get("/browser_lazy").text
    return re.search(r'var TOKEN = "([^"]+)";', html).group(1)


def upload(client, data, filename="Dune.pdf", csrf=None):
    return client.post("/upload", data={"book": (io.BytesIO(data), filename)},
                       headers={"X-CSRFToken": csrf if csrf is not None else token(client)},
                       content_type="multipart/form-data")


def test_upload(app, client, tmp_path):
    response = upload(client, pdf_bytes(tmp_path, "Dune"))
    assert response.status_code == 200
    book = app.bookdir.find_book_by_filename("Incoming/Dune.pdf")
    assert response.json == {"filename": "Incoming/Dune.pdf", "sha1": book.sha1}


def test_upload_of_a_known_book(app, client, tmp_path):
    """ a copy of a book of the library: a duplicate, not a new book """
    data = pdf_bytes(tmp_path, "Dune")
    make_pdf(Path(app.config["BOOK_DIR"]) / "Dune.pdf", title="Dune")
    app.bookdir.rescan()
    response = upload(client, data)
    assert response.json == {"filename": "Incoming/Dune.pdf", "sha1": None}


def test_upload_errors(app, client, tmp_path):
    data = pdf_bytes(tmp_path, "Dune")
    assert upload(client, data, csrf="").status_code == 400
    response = upload(client, b"not a PDF file")
    assert response.status_code == 400 and "not a PDF file" in response.json["error"]
    response = client.post("/upload", headers={"X-CSRFToken": token(client)})
    assert response.status_code == 400 and response.json["error"] == "Aucun fichier reçu."
    app.config["UPLOAD_MAX_SIZE"] = 100
    response = upload(client, data)
    assert response.status_code == 413 and "0 Mo au plus" in response.json["error"]
    assert not (Path(app.config["BOOK_DIR"]) / "Incoming").exists()


def test_upload_requires_login(app):
    assert app.test_client().post("/upload").status_code == 302


def test_upload_larger_than_max_content_length(app, client, tmp_path):
    """ a book may be larger than the other requests (MAX_CONTENT_LENGTH) """
    app.config["MAX_CONTENT_LENGTH"] = 100
    assert upload(client, pdf_bytes(tmp_path, "Dune")).status_code == 200


def test_drop_zone_in_the_library(client):
    html = client.get("/browser_lazy").text
    assert 'id="drop-zone"' in html and "« Incoming »" in html
