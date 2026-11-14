import logging
import re
from pathlib import Path

import pytest

from tests.conftest import make_pdf


@pytest.fixture
def book(app):
    """ Science/O'Reilly.pdf, and a few other files """
    root = Path(app.config["BOOK_DIR"])
    make_pdf(root / "Science" / "O'Reilly.pdf", title="A")
    make_pdf(root / "Art" / "b.pdf", title="B")
    make_pdf(root / "b.pdf", title="C")
    app.bookdir.rescan()
    return app.bookdir.find_book_by_filename("Science/O'Reilly.pdf")


def token(client, url, prefix=""):
    """ The CSRF token of a form of the page at url """
    name = f"{prefix}-csrf_token" if prefix else "csrf_token"
    html = client.get(url).text
    return re.search(rf'name="{name}" (?:type="hidden" )?value="([^"]+)"', html).group(1)


def post(client, book, action, prefix, **data):
    page = f"/bookadmin/{book.sha1}"
    data = {f"{prefix}-{k}": v for k, v in data.items()}
    data[f"{prefix}-csrf_token"] = token(client, page, prefix)
    return client.post(f"{page}/{action}", data=data)


def test_book_page_shows_file_actions(app, client, book):
    html = client.get(f"/bookadmin/{book.sha1}").text
    assert "Actions sur le fichier" in html
    assert 'value="O&#39;Reilly.pdf"' in html
    # categories: the root and the existing directories, current one selected
    assert re.findall(r'<option (?:selected )?value="([^"]*)"', html) == ["", "Art", "Science"]
    assert '<option selected value="Science">' in html
    # confirmation of the trash, the file name escaped for javascript
    assert "return confirm(" in html and "O\\u0027Reilly.pdf" in html


def test_rename(app, client, book, caplog):
    caplog.set_level(logging.WARNING)
    root = Path(app.config["BOOK_DIR"])
    response = post(client, book, "rename", "rename", name="New name")
    assert response.status_code == 302 and response.location == f"/bookadmin/{book.sha1}"
    assert (root / "Science" / "New name.pdf").exists()
    assert book.filename == "Science/New name.pdf"
    assert "Fichier renommé : Science/New name.pdf" in client.get(response.location).text
    # logged with the user name
    assert "test: rename 'Science/O'Reilly.pdf' -> 'Science/New name.pdf'" in caplog.text


@pytest.mark.parametrize("name, message", [
    ("../x", "Opération refusée"),
    ("", "Nouveau nom : Nom de fichier attendu."),
])
def test_rename_refused(app, client, book, name, message):
    response = post(client, book, "rename", "rename", name=name)
    assert message in client.get(response.location).text
    assert book.filename == "Science/O'Reilly.pdf"
    assert (Path(app.config["BOOK_DIR"]) / "Science" / "O'Reilly.pdf").exists()


def test_rename_to_an_existing_file(app, client, book):
    make_pdf(Path(app.config["BOOK_DIR"]) / "Science" / "taken.pdf", title="taken")
    response = post(client, book, "rename", "rename", name="taken.pdf")
    assert "destination already exists" in client.get(response.location).text
    assert book.filename == "Science/O'Reilly.pdf"


def test_move(app, client, book):
    response = post(client, book, "move", "move", category="Art")
    assert book.filename == "Art/O'Reilly.pdf" and book.category == "Art"
    assert "Fichier déplacé : Art/O&#39;Reilly.pdf" in client.get(response.location).text
    post(client, book, "move", "move", category="")
    assert book.filename == "O'Reilly.pdf"


def test_move_to_an_unknown_category(app, client, book):
    (Path(app.config["BOOK_DIR"]) / "Trash").mkdir()
    response = post(client, book, "move", "move", category="Trash")
    assert "Catégorie : Catégorie inconnue." in client.get(response.location).text
    assert book.filename == "Science/O'Reilly.pdf"


def test_trash(app, client, book):
    root = Path(app.config["BOOK_DIR"])
    response = post(client, book, "trash", "trash")
    assert (root / "Trash" / "Science" / "O'Reilly.pdf").exists()
    assert not book.present
    html = client.get(response.location).text
    assert "Fichier mis à la corbeille : Trash/Science/O&#39;Reilly.pdf" in html
    # a missing book has no file actions
    assert "Actions sur le fichier" not in html


@pytest.mark.parametrize("action", ["rename", "move", "trash"])
def test_file_actions_require_csrf_token(app, client, book, action):
    response = client.post(f"/bookadmin/{book.sha1}/{action}",
                           data={"rename-name": "x", "move-category": "Art"})
    assert "Formulaire expiré ou invalide" in client.get(response.location).text
    assert book.filename == "Science/O'Reilly.pdf" and book.present


@pytest.mark.parametrize("action", ["rename", "move", "trash"])
def test_file_actions_unknown_book(client, action):
    assert client.post(f"/bookadmin/{'0' * 40}/{action}").status_code == 404


@pytest.mark.parametrize("url", ["/bookadmin/0/rename", "/bookadmin/0/move",
                                 "/bookadmin/0/trash", "/bookadmin/duplicates/trash"])
def test_file_actions_require_login(app, url):
    response = app.test_client().post(url)
    assert response.status_code == 302 and response.location.endswith("/login")


def test_trash_duplicate(app, client, book):
    root = Path(app.config["BOOK_DIR"])
    make_pdf(root / "copy" / "a.pdf", title="A")
    app.bookdir.rescan()
    # no confirmation dialog for a copy
    assert "confirm(" not in client.get("/bookadmin/duplicates").text

    response = client.post("/bookadmin/duplicates/trash", data={
        "csrf_token": token(client, "/bookadmin/duplicates"),
        "filename": "copy/a.pdf",
    })
    assert response.location == "/bookadmin/duplicates"
    assert (root / "Trash" / "copy" / "a.pdf").exists()
    assert app.bookdir.duplicates == [] and book.present
    html = client.get(response.location).text
    assert "Copie mise à la corbeille : Trash/copy/a.pdf" in html
    assert "Aucun doublon" in html


def test_trash_duplicate_refused(app, client, book):
    make_pdf(Path(app.config["BOOK_DIR"]) / "copy" / "a.pdf", title="A")
    app.bookdir.rescan()
    # a book is not a duplicate
    response = client.post("/bookadmin/duplicates/trash", data={
        "csrf_token": token(client, "/bookadmin/duplicates"),
        "filename": book.filename,
    })
    assert "Opération refusée" in client.get(response.location).text
    assert book.present
    # without CSRF token
    response = client.post("/bookadmin/duplicates/trash", data={"filename": "copy/a.pdf"})
    assert "Formulaire expiré ou invalide" in client.get(response.location).text
    assert len(app.bookdir.duplicates) == 1


def test_trash_page(app, client, book):
    assert "La corbeille est vide." in client.get("/bookadmin/trash").text
    assert "dans la corbeille" not in client.get("/bookadmin/").text

    app.bookdir.trash_book(book.sha1)
    html = client.get("/bookadmin/").text
    assert '<a href="/bookadmin/trash">1 dans la corbeille</a>' in html
    html = client.get("/bookadmin/trash").text
    assert "1 fichier dans la corbeille." in html
    assert "<td>Science/O&#39;Reilly.pdf</td>" in html
    assert 'name="filename" value="Trash/Science/O&#39;Reilly.pdf"' in html


def test_book_list_summary_with_everything(app, client, book):
    root = Path(app.config["BOOK_DIR"])
    make_pdf(root / "copy.pdf", title="B")
    make_pdf(root / "gone.pdf", title="gone")
    app.bookdir.rescan()
    app.bookdir.trash_book(book.sha1)
    (root / "gone.pdf").unlink()
    app.bookdir.rescan()
    html = client.get("/bookadmin/").text
    assert "4 livres, dont 2 absents du répertoire, " \
        '<a href="/bookadmin/duplicates">1 en doublon</a> et ' \
        '<a href="/bookadmin/trash">1 dans la corbeille</a>.' in html


def test_restore(app, client, book, caplog):
    caplog.set_level(logging.WARNING)
    root = Path(app.config["BOOK_DIR"])
    book.tags = "algo"
    app.bookdir.trash_book(book.sha1)

    response = client.post("/bookadmin/trash/restore", data={
        "csrf_token": token(client, "/bookadmin/trash"),
        "filename": "Trash/Science/O'Reilly.pdf",
    })
    assert response.location == "/bookadmin/trash"
    assert (root / "Science" / "O'Reilly.pdf").exists()
    # the book is back, with its settings
    assert book.present and book.filename == "Science/O'Reilly.pdf" and book.tags == "algo"
    html = client.get(response.location).text
    assert "Fichier restauré : Science/O&#39;Reilly.pdf" in html
    assert "La corbeille est vide." in html
    assert "test: restore 'Trash/Science/O'Reilly.pdf' -> 'Science/O'Reilly.pdf'" in caplog.text


def test_restore_refused(app, client, book):
    root = Path(app.config["BOOK_DIR"])
    app.bookdir.trash_book(book.sha1)
    make_pdf(root / "Science" / "O'Reilly.pdf", title="another one")
    tok = token(client, "/bookadmin/trash")

    # the original path is taken
    response = client.post("/bookadmin/trash/restore",
                           data={"csrf_token": tok, "filename": "Trash/Science/O'Reilly.pdf"})
    assert "destination already exists" in client.get(response.location).text
    # not a file of the trash
    response = client.post("/bookadmin/trash/restore",
                           data={"csrf_token": tok, "filename": "b.pdf"})
    assert "Opération refusée" in client.get(response.location).text
    # without CSRF token
    response = client.post("/bookadmin/trash/restore",
                           data={"filename": "Trash/Science/O'Reilly.pdf"})
    assert "Formulaire expiré ou invalide" in client.get(response.location).text
    assert (root / "Trash" / "Science" / "O'Reilly.pdf").exists()


@pytest.mark.parametrize("method, url", [("get", "/bookadmin/trash"),
                                         ("post", "/bookadmin/trash/restore")])
def test_trash_pages_require_login(app, method, url):
    response = getattr(app.test_client(), method)(url)
    assert response.status_code == 302 and response.location.endswith("/login")


def test_trash_page_buttons(app, client, book):
    html = client.get("/bookadmin/trash").text
    assert "Vider la corbeille" not in html
    app.bookdir.trash_book(book.sha1)
    html = client.get("/bookadmin/trash").text
    assert "Supprimer" in html and "Vider la corbeille" in html
    assert 'confirm("Supprimer d\\u00e9finitivement \\u00ab Science/O\\u0027Reilly.pdf \\u00bb ?")' in html
    assert 'confirm("Vider la corbeille : supprimer d\\u00e9finitivement 1 fichier ?")' in html


def test_delete_from_trash(app, client, book, caplog):
    caplog.set_level(logging.WARNING)
    root = Path(app.config["BOOK_DIR"])
    app.bookdir.trash_book(book.sha1)

    response = client.post("/bookadmin/trash/delete", data={
        "csrf_token": token(client, "/bookadmin/trash"),
        "filename": "Trash/Science/O'Reilly.pdf",
    })
    assert response.location == "/bookadmin/trash"
    assert not (root / "Trash" / "Science" / "O'Reilly.pdf").exists()
    html = client.get(response.location).text
    assert "Fichier supprimé définitivement : Trash/Science/O&#39;Reilly.pdf" in html
    assert "La corbeille est vide." in html
    assert "test: delete 'Trash/Science/O'Reilly.pdf' -> 'Trash/Science/O'Reilly.pdf'" in caplog.text
    # the book stays in the database, missing
    assert not book.present


def test_delete_from_trash_refused(app, client, book):
    root = Path(app.config["BOOK_DIR"])
    app.bookdir.trash_book(book.sha1)
    tok = token(client, "/bookadmin/trash")
    # a file of the library is never deleted
    response = client.post("/bookadmin/trash/delete", data={"csrf_token": tok, "filename": "b.pdf"})
    assert "Opération refusée" in client.get(response.location).text
    assert (root / "b.pdf").exists()
    # without CSRF token
    response = client.post("/bookadmin/trash/delete", data={"filename": "Trash/Science/O'Reilly.pdf"})
    assert "Formulaire expiré ou invalide" in client.get(response.location).text
    assert (root / "Trash" / "Science" / "O'Reilly.pdf").exists()


def test_empty_trash(app, client, book, caplog):
    caplog.set_level(logging.WARNING)
    root = Path(app.config["BOOK_DIR"])
    make_pdf(root / "copy.pdf", title="B")
    app.bookdir.rescan()
    app.bookdir.trash_book(book.sha1)
    app.bookdir.trash_duplicate("copy.pdf")

    response = client.post("/bookadmin/trash/empty", data={"csrf_token": token(client, "/bookadmin/trash")})
    assert response.location == "/bookadmin/trash"
    html = client.get(response.location).text
    assert "Corbeille vidée : 2 fichiers supprimés définitivement." in html
    assert "La corbeille est vide." in html
    assert not list((root / "Trash").rglob("*.pdf"))
    # the library is untouched
    assert sorted(b.filename for b in app.bookdir.get_booklist()) == ["Art/b.pdf", "b.pdf"]
    assert "test: empty the trash -> '2'" in caplog.text


def test_empty_trash_requires_csrf_token(app, client, book):
    app.bookdir.trash_book(book.sha1)
    response = client.post("/bookadmin/trash/empty")
    assert "Formulaire expiré ou invalide" in client.get(response.location).text
    assert (Path(app.config["BOOK_DIR"]) / "Trash" / "Science" / "O'Reilly.pdf").exists()


@pytest.mark.parametrize("url", ["/bookadmin/trash/delete", "/bookadmin/trash/empty"])
def test_trash_deletion_requires_login(app, url):
    response = app.test_client().post(url)
    assert response.status_code == 302 and response.location.endswith("/login")


def test_trash_page_total_size(app, client):
    trash = Path(app.config["BOOK_DIR"]) / "Trash"
    # hidden when the trash is empty
    assert "Taille totale" not in client.get("/bookadmin/trash").text

    (trash / "Science").mkdir(parents=True)
    (trash / "a.pdf").write_bytes(b"a" * (1024 * 1024))
    (trash / "Science" / "b.pdf").write_bytes(b"b" * (256 * 1024))
    html = client.get("/bookadmin/trash").text
    assert "Taille totale : 1.25&nbsp;Mo" in html
    # between the title and the table
    assert html.index("<h2>Corbeille</h2>") < html.index("Taille totale") \
        < html.index("<table")
