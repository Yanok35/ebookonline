import json
import os
import re
import shutil
from pathlib import Path

import pytest

from srcs.cache import available_backends
from tests.conftest import make_pdf, write_jpeg


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
    html = client.get(response.location).text
    assert "Miniature en cours de régénération" in html
    assert "la page se recharge dès qu&#39;elle est prête" in html


def test_reset_thumbnail_backends(app, client, book, monkeypatch):
    html = client.get(f"/bookadmin/{book.sha1}").text
    select = re.search(r'<select[^>]*name="reset-backend".*?</select>', html, re.S).group(0)
    assert re.findall(r'<option (?:selected )?value="([^"]*)"', select) == \
        [""] + list(available_backends())
    assert "Automatique (le premier qui réussit)" in select

    # a chosen backend is queued with the request; none: each one in turn
    app.cache.requests.clear()
    app.cache.backends.clear()
    for backend in ("wand", ""):
        response = client.post(f"/reset-thumbnail/{book.sha1}", data={
            "reset-csrf_token": reset_csrf_token(client, book), "reset-backend": backend})
    assert app.cache.backends == ["wand", None]
    assert "(Automatique (le premier qui réussit))" in client.get(response.location).text


def test_reset_thumbnail_unavailable_backend(app, client, book, monkeypatch):
    # gs is not installed: Ghostscript is not proposed, and refused
    monkeypatch.setattr("srcs.cache.shutil.which", lambda name: None)
    html = client.get(f"/bookadmin/{book.sha1}").text
    assert 'value="ghostscript"' not in html
    app.cache.requests.clear()
    for backend in ("ghostscript", "unknown"):
        response = client.post(f"/reset-thumbnail/{book.sha1}", data={
            "reset-csrf_token": reset_csrf_token(client, book), "reset-backend": backend})
        assert app.cache.requests == []
        assert "Méthode de génération indisponible." in client.get(response.location).text


def test_thumbnail_info(app, client, book):
    html = client.get(f"/bookadmin/{book.sha1}").text
    assert "Pas de miniature : image de remplacement." in html
    write_jpeg(Path(app.cache.get_thumbname(book.sha1)), 300, 424)
    size = os.path.getsize(app.cache.get_thumbname(book.sha1))
    html = client.get(f"/bookadmin/{book.sha1}").text
    assert "300&nbsp;×&nbsp;424&nbsp;pixels" in html
    assert f"{size / 1024:.1f}&nbsp;Ko ({size} octets)" in html
    # the groups of actions
    assert html.index("<h2>Miniature</h2>") < html.index("<h3>Extraire du PDF</h3>") \
        < html.index('name="reset-backend"') < html.index("<h3>Insérer depuis une image</h3>") \
        < html.index('name="cover-image"')


def test_cmyk_thumbnail_info(app, client, book):
    sof = b"\xff\xc0\x00\x11\x08" + (450).to_bytes(2, "big") + (300).to_bytes(2, "big") + b"\x04"
    Path(app.cache.get_thumbname(book.sha1)).write_bytes(b"\xff\xd8" + sof)
    html = client.get(f"/bookadmin/{book.sha1}").text
    assert "CMYK (couleurs faussées : à régénérer)" in html


def test_unreadable_thumbnail_info(app, client, book):
    Path(app.cache.get_thumbname(book.sha1)).write_bytes(b"not an image")
    html = client.get(f"/bookadmin/{book.sha1}").text
    assert "Image illisible," in html and "(12 octets)" in html


def test_thumbnail_state(app, client, book):
    """ The book page waits for a missing thumbnail, then reloads """
    url = f"/bookadmin/{book.sha1}/thumbnail"
    html = client.get(f"/bookadmin/{book.sha1}").text
    assert f'data-poll="{url}"' in html
    assert client.get(url).get_json() == {"ready": False}
    write_jpeg(Path(app.cache.get_thumbname(book.sha1)), 30, 40)
    assert client.get(url).get_json() == {"ready": True}
    # no wait when the thumbnail exists
    assert f'data-poll="{url}"' not in client.get(f"/bookadmin/{book.sha1}").text


def test_thumbnail_state_errors(app, client, book):
    assert client.get("/bookadmin/" + "0" * 40 + "/thumbnail").status_code == 404
    anonymous = app.test_client()
    assert anonymous.get(f"/bookadmin/{book.sha1}/thumbnail").status_code == 302
    # no wait when the thumbnail can not be made
    app.cache.writable = False
    assert "data-poll" not in client.get(f"/bookadmin/{book.sha1}").text.split("thumbnail-info")[1][:200]


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


def test_duplicates_page_total_size(app, client):
    root = Path(app.config["BOOK_DIR"])
    # hidden without duplicates
    assert "Taille totale" not in client.get("/bookadmin/duplicates").text

    (root / "a.pdf").write_bytes(b"%PDF-" + b"a" * (1024 * 1024 - 5))
    (root / "b.pdf").write_bytes(b"%PDF-" + b"b" * (512 * 1024 - 5))
    for name in ["a", "b"]:
        shutil.copy(root / f"{name}.pdf", root / f"copy-of-{name}.pdf")
    shutil.copy(root / "a.pdf", root / "z.pdf")
    app.bookdir.rescan()

    # the copies only: 2 x 1 MiB + 0.5 MiB
    html = client.get("/bookadmin/duplicates").text
    assert "Taille totale des copies : 2.50&nbsp;Mo" in html
    # between the title and the note
    assert html.index("<h2>Doublons</h2>") < html.index("Taille totale") \
        < html.index("Fichiers au contenu identique")


def test_book_list_total_size(app, client):
    root = Path(app.config["BOOK_DIR"])
    # hidden without books
    assert "Taille totale" not in client.get("/bookadmin/").text

    (root / "a.pdf").write_bytes(b"%PDF-" + b"a" * (1024 * 1024 - 5))
    (root / "b.pdf").write_bytes(b"%PDF-" + b"b" * (512 * 1024 - 5))
    (root / "gone.pdf").write_bytes(b"%PDF-" + b"c" * (1024 * 1024 - 5))
    app.bookdir.rescan()
    os.remove(root / "gone.pdf")
    app.bookdir.rescan()

    # the missing book is not counted
    html = client.get("/bookadmin/").text
    assert "Taille totale : 1.50&nbsp;Mo" in html
    # between the title and the table
    assert html.index("<h2>Liste des livres</h2>") < html.index("Taille totale") \
        < html.index("<table")


def test_book_page_cover_links_to_the_reader(app, client, book):
    html = client.get(f"/bookadmin/{book.sha1}").text
    reader = f"/reader/{book.sha1}"
    assert f'<a href="{reader}" title="Lire le livre">' in html
    assert client.get(reader).status_code == 200

    # missing PDF: nothing to read
    os.remove(Path(app.config["BOOK_DIR"]) / "Python Algorithms.pdf")
    app.bookdir.rescan()
    html = client.get(f"/bookadmin/{book.sha1}").text
    assert "/reader/" not in html and f'src="/images/{book.sha1}"' in html


def test_book_page_name_after_the_pattern(app, client, book):
    url = f"/bookadmin/{book.sha1}"
    assert "Pas de nom selon le modèle : titre manquant." in client.get(url).text

    book.title, book.authors, book.year = "Python Algorithms", ["Magnus Lie Hetland"], 2010
    html = client.get(url).text
    assert "Selon le modèle : <q>Python Algorithms - Hetland, Magnus Lie, 2010.pdf</q>" in html
    assert re.search(r'data-field="rename-name"\s+data-value="Python Algorithms - '
                     r'Hetland, Magnus Lie, 2010.pdf"', html)

    # renamed with it: conform, same modification time
    root = Path(app.config["BOOK_DIR"])
    mtime = os.stat(root / book.filename).st_mtime
    token = re.search(r'name="rename-csrf_token" type="hidden" value="([^"]+)"', html).group(1)
    client.post(f"/bookadmin/{book.sha1}/rename", data={
        "rename-csrf_token": token, "rename-name": "Python Algorithms - Hetland, Magnus Lie, 2010.pdf"})
    assert book.filename == "Python Algorithms - Hetland, Magnus Lie, 2010.pdf"
    assert os.stat(root / book.filename).st_mtime == mtime
    assert "Nom conforme au modèle." in client.get(url).text


def test_book_page_name_after_the_pattern_taken(app, client, book):
    """ The name after the pattern is the one of another file: suffix (2) """
    root = Path(app.config["BOOK_DIR"])
    book.title, book.authors, book.year = "Python Algorithms", ["Magnus Lie Hetland"], 2010
    make_pdf(root / "Python Algorithms - Hetland, Magnus Lie, 2010.pdf", title="other")
    app.bookdir.rescan()
    url = f"/bookadmin/{book.sha1}"
    html = client.get(url).text
    assert "Selon le modèle : <q>Python Algorithms - Hetland, Magnus Lie, 2010 (2).pdf</q>" in html
    assert "(« Python Algorithms - Hetland, Magnus Lie, 2010.pdf » existe déjà)" in html

    token = re.search(r'name="rename-csrf_token" type="hidden" value="([^"]+)"', html).group(1)
    client.post(f"/bookadmin/{book.sha1}/rename", data={
        "rename-csrf_token": token, "rename-name": "Python Algorithms - Hetland, Magnus Lie, 2010 (2).pdf"})
    assert book.filename == "Python Algorithms - Hetland, Magnus Lie, 2010 (2).pdf"
    html = client.get(url).text
    assert "Nom conforme au modèle" in html and "est pris par un autre fichier" in html
