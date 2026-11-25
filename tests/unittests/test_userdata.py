""" The data of the users, userdata.db (srcs/userdata.py), and the API of the notes """

import json
import re
from pathlib import Path

import pytest

from srcs.userdata import (USERDATA_VERSION, UserData, UserDataError, clean_notes)
from tests.conftest import make_pdf

NOTE = {"id": "n-1", "page": 3, "ratio": 0.25, "quote": "", "text": "Relire"}


# --- srcs/userdata.py

def test_notes_saved_and_read_again(tmp_path):
    path = tmp_path / "userdata.db"
    data = UserData(str(path))
    assert data.notes("alice", "a" * 40) == []
    kept = data.set_notes("alice", "a" * 40, [NOTE])
    assert kept[0]["text"] == "Relire" and kept[0]["created"] == kept[0]["updated"]
    db = json.loads(path.read_text())
    assert db["version"] == USERDATA_VERSION and db["min_reader_version"] == 1
    assert db["users"]["alice"]["notes"]["a" * 40][0]["id"] == "n-1"
    # read again; each user their own notes
    again = UserData(str(path))
    assert again.notes("alice", "a" * 40) == kept and again.notes("bob", "a" * 40) == []
    # written whole, atomically: no temporary file left
    assert [p.name for p in tmp_path.iterdir()] == ["userdata.db"]


def test_empty_notes_dropped(tmp_path):
    data = UserData(str(tmp_path / "userdata.db"))
    data.set_notes("alice", "b" * 40, [NOTE])
    assert data.set_notes("alice", "b" * 40, [dict(NOTE, text="  ")]) == []
    assert "b" * 40 not in json.loads((tmp_path / "userdata.db").read_text())["users"]["alice"]["notes"]


def test_dates_of_the_notes(monkeypatch):
    import srcs.userdata as userdata

    monkeypatch.setattr(userdata, "_now", lambda: "T1")
    first = clean_notes([NOTE, dict(NOTE, id="n-2")])
    monkeypatch.setattr(userdata, "_now", lambda: "T2")
    second = clean_notes([NOTE, dict(NOTE, id="n-2", text="Changée")], first)
    assert [(n["created"], n["updated"]) for n in second] == [("T1", "T1"), ("T1", "T2")]


@pytest.mark.parametrize("notes, message", [
    ({"id": "x"}, "a list of notes"),
    (["note"], "must be an object"),
    ([dict(NOTE, id="")], "invalid note id"),
    ([NOTE, NOTE], "used twice"),
    ([dict(NOTE, page=0)], "invalid page"),
    ([dict(NOTE, page=True)], "invalid page"),
    ([dict(NOTE, ratio=1.5)], "invalid height"),
    ([dict(NOTE, ratio=float("nan"))], "invalid height"),
    ([dict(NOTE, quote="x" * 257)], "invalid quotation"),
    ([dict(NOTE, text="x" * 10001)], "invalid text"),
    ([dict(NOTE, id=f"n-{i}") for i in range(1001)], "too many notes"),
])
def test_invalid_notes(notes, message):
    with pytest.raises(UserDataError, match=message):
        clean_notes(notes)


def test_move_book(tmp_path):
    data = UserData(str(tmp_path / "userdata.db"))
    data.set_notes("alice", "old", [NOTE, dict(NOTE, id="n-2", page=1)])
    data.set_notes("bob", "old", [NOTE])
    assert data.move_book("old", "new", page_offset=1) == 2
    again = UserData(str(tmp_path / "userdata.db"))
    assert [n["page"] for n in again.notes("alice", "new")] == [4, 2]
    assert again.notes("alice", "old") == [] and len(again.notes("bob", "new")) == 1
    # back (the original restored): never before the first page
    data.move_book("new", "old", page_offset=-3)
    assert [n["page"] for n in data.notes("alice", "old")] == [1, 1]
    assert data.move_book("unknown", "other") == 0


def test_newer_file_read_only(tmp_path, caplog):
    path = tmp_path / "userdata.db"
    path.write_text(json.dumps({"version": USERDATA_VERSION + 1, "min_reader_version": 1,
                                "users": {"alice": {"notes": {"s": [NOTE]}}}, "pins": []}))
    data = UserData(str(path))
    assert data.read_only and data.newer_version == USERDATA_VERSION + 1
    assert data.notes("alice", "s")[0]["id"] == "n-1"
    # kept in memory only: the newer file is not rewritten
    before = path.read_text()
    data.set_notes("alice", "s", [])
    assert path.read_text() == before and data.notes("alice", "s") == []


def test_file_of_an_unreadable_version(tmp_path):
    path = tmp_path / "userdata.db"
    path.write_text(json.dumps({"version": USERDATA_VERSION + 1,
                                "min_reader_version": USERDATA_VERSION + 1, "users": {}}))
    with pytest.raises(UserDataError, match="upgrade ebookonline"):
        UserData(str(path))


def test_damaged_file(tmp_path):
    path = tmp_path / "userdata.db"
    path.write_text("{not json")
    with pytest.raises(UserDataError, match="can not read"):
        UserData(str(path))


# --- the API, the server

@pytest.fixture
def book(app):
    make_pdf(Path(app.config["BOOK_DIR"]) / "a.pdf")
    app.bookdir.rescan()
    return app.bookdir.find_book_by_filename("a.pdf")


def notes_token(client, book):
    html = client.get(f"/reader/{book.sha1}").text
    return re.search(r'const NOTES_TOKEN = "([^"]+)";', html).group(1)


def put(client, sha1, notes, token):
    return client.put(f"/api/notes/{sha1}", json={"notes": notes}, headers={"X-CSRFToken": token})


def test_notes_api(app, client, book):
    token = notes_token(client, book)
    assert client.get(f"/api/notes/{book.sha1}").json == {"notes": []}
    response = put(client, book.sha1, [NOTE], token)
    assert response.status_code == 200 and response.json["notes"][0]["text"] == "Relire"
    assert client.get(f"/api/notes/{book.sha1}").json["notes"][0]["id"] == "n-1"
    # in userdata.db, under the login of the user
    db = json.loads(Path(app.config["USERDATA_DB"]).read_text())
    assert list(db["users"]) == ["test"]
    # another user: not their notes
    other = app.test_client()
    with other.session_transaction() as session:
        session["username"] = "other"
    assert other.get(f"/api/notes/{book.sha1}").json == {"notes": []}


def test_notes_api_refusals(app, client, book):
    token = notes_token(client, book)
    assert put(client, book.sha1, [NOTE], "bad").status_code == 400
    assert put(client, "0" * 40, [NOTE], token).status_code == 404
    response = put(client, book.sha1, [dict(NOTE, ratio=2)], token)
    assert response.status_code == 400 and "invalid height" in response.json["error"]
    assert client.put(f"/api/notes/{book.sha1}", data="x",
                      headers={"X-CSRFToken": token}).status_code == 400
    # not logged in
    assert app.test_client().get(f"/api/notes/{book.sha1}").status_code == 401


def test_reader_saves_the_notes_on_the_server(client, book):
    html = client.get(f"/reader/{book.sha1}").text
    assert f'const NOTES_URL = "/api/notes/{book.sha1}";' in html
    assert '"X-CSRFToken": NOTES_TOKEN' in html


def test_invalid_login_refused_at_startup(app, monkeypatch):
    from app import create_app

    monkeypatch.setenv("EBOOKONLINE_CREDENTIALS", json.dumps({"bad/name": "hash"}))
    with pytest.raises(RuntimeError, match="CREDENTIALS: invalid login 'bad/name'"):
        create_app()
    monkeypatch.setenv("EBOOKONLINE_CREDENTIALS", json.dumps({"élise.d@home": "hash"}))
    create_app()


def test_pins_of_each_user(app, client, book):
    other = app.test_client()
    with other.session_transaction() as session:
        session["username"] = "other"
    assert client.post("/pinbook", data={"id": book.sha1}).json == {"pinned": True}
    db = json.loads(Path(app.config["USERDATA_DB"]).read_text())
    assert db["users"]["test"]["pins"] == [book.sha1]
    # book.db: no longer changed by a pin
    assert not app.bookdir.find_book_by_sha1(book.sha1).bookmarked

    def pinned_icon(c):
        return "bookmark-active.svg" in c.get("/browser_subset?subset-id=0").text

    assert pinned_icon(client) and not pinned_icon(other)
    # the filter "épinglés" of the search
    def pinned_search(c):
        return json.loads(c.get("/browser_search?pat=&pinned=true").text)["body"]

    assert book.sha1 in pinned_search(client) and book.sha1 not in pinned_search(other)
    # the book page
    assert "<dt>Épinglé</dt><dd>oui</dd>" in client.get(f"/bookadmin/{book.sha1}").text
    assert "<dt>Épinglé</dt><dd>non</dd>" in other.get(f"/bookadmin/{book.sha1}").text
    # unpinned
    assert client.post("/pinbook", data={"id": book.sha1}).json == {"pinned": False}
    assert client.post("/pinbook", data={"id": "0" * 40}).status_code == 404


def test_move_book_states_and_pins(tmp_path):
    data = UserData(str(tmp_path / "userdata.db"))
    data.set_state("alice", {"documentId": "old", "pageNumber": 5})
    data.toggle_pin("alice", "old")
    data.toggle_pin("bob", "other")
    assert data.move_book("old", "new", page_offset=1) == 1
    again = UserData(str(tmp_path / "userdata.db"))
    assert again.state("alice", "new") == {"documentId": "new", "pageNumber": 6}
    assert again.state("alice", "old") is None
    assert again.pins("alice") == {"new"} and again.pins("bob") == {"other"}


def test_import_common_once(tmp_path):
    data = UserData(str(tmp_path / "userdata.db"))
    states = {"s1": {"documentId": "s1", "pageNumber": 2}}
    assert data.import_common(["alice", "bob"], states, ["s1"]) == ["alice", "bob"]
    data.set_state("alice", {"documentId": "s1", "pageNumber": 9})
    # a copy for each one: not shared
    assert data.state("bob", "s1")["pageNumber"] == 2
    # once; a new user gets a copy too
    assert data.import_common(["alice", "bob", "carol"], states, ["s1"]) == ["carol"]
    assert data.state("alice", "s1")["pageNumber"] == 9
