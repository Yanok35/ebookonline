import json
import os

STATE = {
    "documentId": "doc-1",
    "documentName": "a.pdf",
    "pageNumber": 3,
    "positionX": 0,
    "positionY": 120.5,
    "zoom": 1.0,
}


def test_reader_state_requires_login(app):
    client = app.test_client()
    assert client.get("/api/reader/state/doc-1").status_code == 401
    assert client.put("/api/reader/state", json=STATE).status_code == 401


def test_reader_state_is_saved_for_the_user(app, client):
    assert client.get("/api/reader/state/doc-1").status_code == 404
    response = client.put("/api/reader/state", json=STATE)
    assert response.status_code == 200 and response.json["success"]

    db = json.loads(open(app.config["USERDATA_DB"], encoding="utf-8").read())
    assert db["users"]["test"]["states"]["doc-1"]["pageNumber"] == 3
    assert client.get("/api/reader/state/doc-1").json["pageNumber"] == 3
    # reader_states.json: no longer written
    assert not os.path.exists(app.config["STATE_FILE"])
    # another user: their own position
    other = app.test_client()
    with other.session_transaction() as session:
        session["username"] = "other"
    assert other.get("/api/reader/state/doc-1").status_code == 404
    other.put("/api/reader/state", json=dict(STATE, pageNumber=9))
    assert client.get("/api/reader/state/doc-1").json["pageNumber"] == 3
    assert other.get("/api/reader/state/doc-1").json["pageNumber"] == 9


def test_invalid_reader_state(app, client):
    response = client.put("/api/reader/state", json=dict(STATE, pageNumber=0))
    assert response.status_code == 400
    assert not os.path.exists(app.config["USERDATA_DB"])


# --- journal of the reader events

def events(app):
    with open(app.config["READER_EVENTS_FILE"], encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def test_reader_events_are_appended(app, client):
    client.put("/api/reader/state", json=STATE)
    client.put("/api/reader/state", json=dict(STATE, pageNumber=4))
    client.put("/api/reader/state", json=dict(STATE, documentId="doc-2", pageNumber=1))
    logged = events(app)
    assert [(e["doc"], e["page"], e["user"]) for e in logged] == \
        [("doc-1", 3, "test"), ("doc-1", 4, "test"), ("doc-2", 1, "test")]
    # time of the server, in UTC
    assert logged[0]["t"].endswith("+00:00") and len(logged[0]["t"]) == 25


def test_invalid_state_is_not_an_event(app, client):
    client.put("/api/reader/state", json=dict(STATE, pageNumber=0))
    assert not os.path.exists(app.config["READER_EVENTS_FILE"])


def test_reader_events_disabled(app, client):
    app.config["READER_EVENTS_FILE"] = ""
    assert client.put("/api/reader/state", json=STATE).status_code == 200


def test_reader_event_failure_is_logged(app, client, tmp_path, caplog):
    app.config["READER_EVENTS_FILE"] = str(tmp_path / "missing-dir" / "events.jsonl")
    response = client.put("/api/reader/state", json=STATE)
    # the state is saved all the same
    assert response.status_code == 200 and response.json["success"]
    assert "Reader event not logged" in caplog.text


# --- reading position of a book whose file was replaced

def test_move_user_data(app, client):
    from app.api import move_user_data

    client.put("/api/reader/state", json=dict(STATE, pageNumber=3))
    app.userdata.toggle_pin("test", "doc-1")
    with app.test_request_context():
        move_user_data("doc-1", "doc-2", page_offset=1)
        move_user_data("unknown", "doc-3")
    assert client.get("/api/reader/state/doc-1").status_code == 404
    state = client.get("/api/reader/state/doc-2").json
    assert state["pageNumber"] == 4 and state["documentId"] == "doc-2"
    assert client.get("/api/reader/state/doc-3").status_code == 404
    assert app.userdata.pins("test") == {"doc-2"}


# --- positions and pins common to all the users, before userdata.db

def test_common_positions_and_pins_copied_to_each_user(app, monkeypatch, caplog):
    import logging
    from pathlib import Path

    from app import create_app
    from tests.conftest import make_pdf

    caplog.set_level(logging.INFO)
    Path(app.config["STATE_FILE"]).write_text(json.dumps({"doc-1": STATE}))
    make_pdf(Path(app.config["BOOK_DIR"]) / "a.pdf")
    app.bookdir.rescan()
    book = app.bookdir.find_book_by_filename("a.pdf")
    book.bookmarked = True
    app.bookdir.save_db()
    monkeypatch.setenv("EBOOKONLINE_CREDENTIALS", json.dumps({"alice": "h", "bob": "h"}))

    app = create_app()
    for user in ("alice", "bob"):
        assert app.userdata.state(user, "doc-1")["pageNumber"] == 3
        assert app.userdata.pins(user) == {book.sha1}
    assert "Common reading positions (1) and pins (1) copied to the users: alice, bob" in caplog.text
    # once: their changes are kept at the next start, the sources untouched
    app.userdata.toggle_pin("alice", book.sha1)
    app.userdata.set_state("bob", dict(STATE, pageNumber=8))
    app = create_app()
    assert app.userdata.pins("alice") == set() and app.userdata.pins("bob") == {book.sha1}
    assert app.userdata.state("bob", "doc-1")["pageNumber"] == 8
    assert json.loads(Path(app.config["STATE_FILE"]).read_text())["doc-1"]["pageNumber"] == 3
    assert app.bookdir.find_book_by_sha1(book.sha1).bookmarked


def test_common_positions_unreadable(app, monkeypatch, caplog):
    from pathlib import Path

    from app import create_app

    # a directory instead of the file: not imported, done at a next start
    Path(app.config["STATE_FILE"]).mkdir()
    monkeypatch.setenv("EBOOKONLINE_CREDENTIALS", json.dumps({"alice": "h"}))
    app = create_app()
    assert "Common reading positions not imported" in caplog.text
    assert app.userdata.state("alice", "doc-1") is None and "alice" not in app.userdata.users
