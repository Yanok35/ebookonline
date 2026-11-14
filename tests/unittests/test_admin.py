import json
import os
import re
import shutil
from pathlib import Path

import pytest

from tests.conftest import make_pdf


def test_book_list_requires_login(app):
    response = app.test_client().get("/bookadmin/")
    assert response.status_code == 302
    assert response.location.endswith("/login")


def test_book_list(app, client):
    root = Path(app.config["BOOK_DIR"])
    make_pdf(root / "b.pdf")
    make_pdf(root / "Science/a.pdf")
    make_pdf(root / "gone.pdf")
    app.bookdir.rescan()
    os.remove(root / "gone.pdf")
    app.bookdir.rescan()

    response = client.get("/bookadmin/")
    assert response.status_code == 200
    html = response.text
    # every book is listed, missing ones included, sorted by file name
    assert html.index("b.pdf") < html.index("gone.pdf") < html.index("Science/a.pdf")
    for b in app.bookdir.get_all_books():
        assert f'/bookadmin/{b.sha1}"' in html
    assert "3 livres, dont 1 absent du répertoire." in html
    assert html.count('class="badge">absent<') == 1


@pytest.fixture
def book(app):
    """ A book of the library, with its PDF present """
    make_pdf(Path(app.config["BOOK_DIR"]) / "Python Algorithms.pdf")
    app.bookdir.rescan()
    return app.bookdir.find_book_by_filename("Python Algorithms.pdf")


def csrf_token(client, url):
    html = client.get(url).text
    return re.search(r'name="csrf_token" type="hidden" value="([^"]+)"', html).group(1)


def test_book_page_unknown_sha1(client):
    assert client.get("/bookadmin/" + "0" * 40).status_code == 404


def test_book_page_shows_current_values(app, client, book):
    book.tags, book.editor, book.year, book.isbn = "algo", "Apress", 2017, "9781484232200"
    html = client.get(f"/bookadmin/{book.sha1}").text
    for value in ["algo", "Apress", "2017", "9781484232200"]:
        assert f'value="{value}"' in html
    # no year: the field is empty, not 0
    book.year = 0
    assert 'name="year" type="number" value=""' in client.get(f"/bookadmin/{book.sha1}").text


def test_book_page_saves_the_form(app, client, book):
    url = f"/bookadmin/{book.sha1}"
    response = client.post(url, data={
        "csrf_token": csrf_token(client, url),
        "tags": "  algo   python ",
        "editor": " O'Reilly ",
        "year": "2022",
        "isbn": "978-1-0981-1316-2",
    })
    assert response.status_code == 302 and response.location == url

    expected = {"tags": "algo python", "editor": "O'Reilly", "year": 2022, "isbn": "9781098113162"}
    assert {k: getattr(book, k) for k in expected} == expected
    with open(app.config["BOOK_DB"]) as f:
        entry = next(b for b in json.load(f)["booklist"] if b["sha1"] == book.sha1)
    assert {k: entry[k] for k in expected} == expected

    # the confirmation is shown once
    assert "Modifications enregistrées." in client.get(url).text
    assert "Modifications enregistrées." not in client.get(url).text


def test_book_page_rejects_invalid_values(client, book):
    url = f"/bookadmin/{book.sha1}"
    response = client.post(url, data={
        "csrf_token": csrf_token(client, url),
        "tags": "algo", "year": "abc", "isbn": "12",
    })
    assert response.status_code == 200
    assert "Année invalide." in response.text
    assert "ISBN-10 ou ISBN-13 attendu" in response.text
    # the input is kept, nothing is saved
    assert 'value="12"' in response.text
    assert book.tags == "" and book.isbn == ""


def test_book_page_requires_csrf_token(client, book):
    response = client.post(f"/bookadmin/{book.sha1}", data={"tags": "algo"})
    assert response.status_code == 200
    assert "Formulaire expiré ou invalide" in response.text
    assert book.tags == ""


def test_missing_book_page(app, client, book):
    os.remove(Path(app.config["BOOK_DIR"]) / book.filename)
    app.bookdir.rescan()
    html = client.get(f"/bookadmin/{book.sha1}").text
    assert 'class="badge">absent<' in html
    assert "absent du répertoire des livres" in html


def reset_csrf_token(client, book):
    html = client.get(f"/bookadmin/{book.sha1}").text
    return re.search(r'name="reset-csrf_token" type="hidden" value="([^"]+)"', html).group(1)


def test_reset_thumbnail(app, client, book):
    thumbname = Path(app.cache.get_thumbname(book.sha1))
    thumbname.write_bytes(b"old thumbnail")
    app.cache.requests.clear()

    response = client.post(f"/reset-thumbnail/{book.sha1}",
                           data={"reset-csrf_token": reset_csrf_token(client, book)})
    assert response.status_code == 302
    assert response.location == f"/bookadmin/{book.sha1}"
    assert not thumbname.exists()
    pdffile = os.path.join(app.config["BOOK_DIR"], book.filename)
    assert app.cache.requests == [(pdffile, book.sha1)]
    assert "Miniature en cours de régénération" in client.get(response.location).text


def test_reset_missing_thumbnail(app, client, book):
    # no thumbnail yet: it is generated, this is not an error
    app.cache.requests.clear()
    client.post(f"/reset-thumbnail/{book.sha1}",
                data={"reset-csrf_token": reset_csrf_token(client, book)})
    assert len(app.cache.requests) == 1


def test_reset_thumbnail_requires_csrf_token(app, client, book):
    thumbname = Path(app.cache.get_thumbname(book.sha1))
    thumbname.write_bytes(b"old thumbnail")
    app.cache.requests.clear()

    response = client.post(f"/reset-thumbnail/{book.sha1}")
    assert response.status_code == 302
    assert thumbname.exists() and app.cache.requests == []
    assert "Formulaire expiré ou invalide" in client.get(response.location).text


def test_reset_thumbnail_of_a_missing_book(app, client, book):
    token = reset_csrf_token(client, book)
    os.remove(Path(app.config["BOOK_DIR"]) / book.filename)
    app.bookdir.rescan()
    app.cache.requests.clear()

    response = client.post(f"/reset-thumbnail/{book.sha1}", data={"reset-csrf_token": token})
    assert app.cache.requests == []
    html = client.get(response.location).text
    assert "la miniature ne peut pas être régénérée" in html
    # no reset button for a missing book
    assert "reset-csrf_token" not in html


def test_reset_thumbnail_unknown_sha1(client):
    assert client.post("/reset-thumbnail/" + "0" * 40).status_code == 404


def test_book_page_shows_copies(app, client, book):
    root = Path(app.config["BOOK_DIR"])
    html = client.get(f"/bookadmin/{book.sha1}").text
    assert "Copies" not in html

    shutil.copy(root / book.filename, root / "copy.pdf")
    app.bookdir.rescan()
    html = client.get(f"/bookadmin/{book.sha1}").text
    assert "<dt>Copies</dt>" in html and "copy.pdf" in html


def test_duplicates_page(app, client):
    root = Path(app.config["BOOK_DIR"])
    make_pdf(root / "a.pdf")
    make_pdf(root / "b.pdf")
    app.bookdir.rescan()
    assert "Aucun doublon" in client.get("/bookadmin/duplicates").text
    assert "en doublon" not in client.get("/bookadmin/").text

    (root / "z").mkdir()
    shutil.copy(root / "a.pdf", root / "copy-of-a.pdf")
    shutil.copy(root / "a.pdf", root / "z" / "a.pdf")
    app.bookdir.rescan()

    html = client.get("/bookadmin/duplicates").text
    assert "1 livre en doublon." in html
    assert "<li>copy-of-a.pdf" in html and "<li>z/a.pdf" in html
    sha1 = app.bookdir.find_book_by_filename("a.pdf").sha1
    assert f'/bookadmin/{sha1}"' in html

    # the book list links to the page, and marks the book
    html = client.get("/bookadmin/").text
    assert '<a href="/bookadmin/duplicates">1 en doublon</a>' in html
    assert html.count('class="badge duplicate">doublon<') == 1


def test_duplicates_page_requires_login(app):
    assert app.test_client().get("/bookadmin/duplicates").status_code == 302


def test_book_list_summary_with_missing_and_duplicates(app, client):
    root = Path(app.config["BOOK_DIR"])
    make_pdf(root / "a.pdf")
    make_pdf(root / "gone.pdf")
    app.bookdir.rescan()
    shutil.copy(root / "a.pdf", root / "copy.pdf")
    os.remove(root / "gone.pdf")
    app.bookdir.rescan()
    html = client.get("/bookadmin/").text
    assert "2 livres, dont 1 absent du répertoire et" in html
    assert ">1 en doublon</a>." in html


@pytest.fixture
def read_only_app(app, book):
    """ The application on a book.db written by a newer, compatible, version """
    import srcs.book
    from app import create_app

    with open(app.config["BOOK_DB"]) as f:
        db = json.load(f)
    db["version"] = srcs.book.DB_VERSION + 1
    with open(app.config["BOOK_DB"], "w") as f:
        json.dump(db, f)
    app = create_app("default")
    assert app.bookdir.read_only
    return app


def test_read_only_banner(app, client, book):
    for url in ["/bookadmin/", "/bookadmin/duplicates", f"/bookadmin/{book.sha1}"]:
        assert "Site en lecture seule" not in client.get(url).text


def test_read_only_book_page(read_only_app):
    client = read_only_app.test_client()
    with client.session_transaction() as session:
        session["username"] = "test"
    book = read_only_app.bookdir.find_book_by_filename("Python Algorithms.pdf")
    db_content = Path(read_only_app.config["BOOK_DB"]).read_text()

    for url in ["/bookadmin/", "/bookadmin/duplicates", f"/bookadmin/{book.sha1}"]:
        html = client.get(url).text
        assert "Site en lecture seule" in html
        assert "version plus récente d&#39;ebookonline" in html

    url = f"/bookadmin/{book.sha1}"
    client.post(url, data={"csrf_token": csrf_token(client, url), "tags": "algo"})
    html = client.get(url).text
    assert "modifications conservées en mémoire" in html
    assert "Modifications enregistrées." not in html
    # applied in memory, not saved
    assert book.tags == "algo"
    assert Path(read_only_app.config["BOOK_DB"]).read_text() == db_content
