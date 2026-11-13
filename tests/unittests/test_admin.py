import json
import os
import re
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
