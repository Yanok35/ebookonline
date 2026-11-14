"""
The server is read-only when it can not write the book directory, book.db or
the reader states (or when book.db was written by a newer version).
"""
import json
import os
import re
from pathlib import Path

import pytest

from tests.conftest import make_pdf

pytestmark = pytest.mark.skipif(os.geteuid() == 0, reason="root writes anywhere")

STATE = {
    "documentId": "doc-1",
    "documentName": "a.pdf",
    "pageNumber": 3,
    "positionX": 0,
    "positionY": 0,
    "zoom": 1.0,
}


@pytest.fixture
def book_dir_read_only_app(app):
    """ The application, restarted on a book directory it can not write """
    from app import create_app

    root = Path(app.config["BOOK_DIR"])
    make_pdf(root / "Science" / "a.pdf", title="A")
    app.bookdir.rescan()
    for d in [root, root / "Science"]:
        d.chmod(0o555)
    yield create_app("default")
    for d in [root, root / "Science"]:
        d.chmod(0o755)


def logged_in(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "test"
    return client


def test_writable_server_is_not_read_only(app, client):
    assert app.read_only_reasons == [] and not app.bookdir.read_only
    assert "lecture seule" not in app.test_client().get("/login").text
    assert "lecture seule" not in client.get("/browser_lazy").text


def test_read_only_reasons(book_dir_read_only_app):
    app = book_dir_read_only_app
    assert app.bookdir.read_only
    assert app.read_only_reasons == [
        f"Écriture impossible dans le répertoire des livres : {app.config['BOOK_DIR']}"]


def test_state_file_directory_not_writable(app, tmp_path, monkeypatch):
    from app import create_app

    states = tmp_path / "states"
    states.mkdir()
    states.chmod(0o555)
    monkeypatch.setenv("EBOOKONLINE_STATE_FILE", str(states / "reader_states.json"))
    try:
        app = create_app("default")
    finally:
        states.chmod(0o755)
    assert app.read_only_reasons == [
        "Écriture impossible dans le répertoire des positions de lecture "
        f"(reader_states.json) : {states}"]
    assert app.bookdir.read_only


def test_login_page_note(book_dir_read_only_app):
    html = book_dir_read_only_app.test_client().get("/login").text
    note = re.search(r'<p class="read-only-note">(.*?)</p>', html, re.S).group(1)
    assert "Site en lecture seule" in note
    # no path for anonymous users
    assert book_dir_read_only_app.config["BOOK_DIR"] not in html


def test_library_badge(book_dir_read_only_app):
    html = logged_in(book_dir_read_only_app).get("/browser_lazy").text
    badge = re.search(r'<span class="badge read-only-badge"\s+title="([^"]*)">lecture seule</span>',
                      html).group(1)
    assert badge.startswith("Session en lecture seule")
    assert "Écriture impossible dans le répertoire des livres" in badge


def test_pin_is_not_saved(book_dir_read_only_app):
    app = book_dir_read_only_app
    db = Path(app.config["BOOK_DB"])
    content = db.read_text()
    book = app.bookdir.find_book_by_filename("Science/a.pdf")

    response = logged_in(app).post("/pinbook", data={"id": book.sha1})
    assert response.json == {"pinned": True}
    assert db.read_text() == content


def test_reader_state_is_kept_in_memory(book_dir_read_only_app):
    app = book_dir_read_only_app
    client = logged_in(app)
    response = client.put("/api/reader/state", json=STATE)
    assert response.status_code == 200 and response.json["readOnly"]
    assert not Path(app.config["STATE_FILE"]).exists()
    assert client.get("/api/reader/state/doc-1").json["pageNumber"] == 3


def test_memory_state_is_over_the_file(app, tmp_bookdir, monkeypatch):
    from app import create_app

    state_file = Path(app.config["STATE_FILE"])
    state_file.write_text(json.dumps({"doc-1": STATE, "doc-2": dict(STATE, documentId="doc-2")}))
    content = state_file.read_text()
    tmp_bookdir[1].chmod(0o555)
    try:
        app = create_app("default")
    finally:
        tmp_bookdir[1].chmod(0o755)
    client = logged_in(app)

    client.put("/api/reader/state", json=dict(STATE, pageNumber=7))
    assert client.get("/api/reader/state/doc-1").json["pageNumber"] == 7
    assert client.get("/api/reader/state/doc-2").json["pageNumber"] == 3
    assert state_file.read_text() == content


def test_file_operations_are_refused(book_dir_read_only_app, caplog):
    app = book_dir_read_only_app
    client = logged_in(app)
    book = app.bookdir.find_book_by_filename("Science/a.pdf")
    page = f"/bookadmin/{book.sha1}"

    html = client.get(page).text
    assert "Indisponibles : le site est en lecture seule." in html
    assert re.search(r'<input class="danger" disabled id="trash-submit"', html)

    token = re.search(r'name="rename-csrf_token" type="hidden" value="([^"]+)"', html).group(1)
    response = client.post(f"{page}/rename", data={"rename-csrf_token": token,
                                                    "rename-name": "renamed"})
    assert "Opération refusée : le site est en lecture seule" in client.get(response.location).text
    assert (Path(app.config["BOOK_DIR"]) / "Science" / "a.pdf").exists()
    assert "test: rename 'Science/a.pdf' refused: read-only mode" in caplog.text


def test_trash_buttons_are_disabled(book_dir_read_only_app):
    app = book_dir_read_only_app
    root = Path(app.config["BOOK_DIR"])
    root.chmod(0o755)
    make_pdf(root / "Trash" / "b.pdf", title="B")
    html = logged_in(app).get("/bookadmin/trash").text
    assert html.count(" disabled") == 3
