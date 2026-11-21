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


def test_reader_state_is_saved_in_state_file(app, client, tmp_bookdir):
    state_file = tmp_bookdir[0] / "reader_states.json"
    assert app.config["STATE_FILE"] == str(state_file)

    assert client.get("/api/reader/state/doc-1").status_code == 404
    response = client.put("/api/reader/state", json=STATE)
    assert response.status_code == 200 and response.json["success"]

    assert json.loads(state_file.read_text())["doc-1"]["pageNumber"] == 3
    assert client.get("/api/reader/state/doc-1").json["pageNumber"] == 3


def test_invalid_reader_state(client, tmp_bookdir):
    response = client.put("/api/reader/state", json=dict(STATE, pageNumber=0))
    assert response.status_code == 400
    assert not (tmp_bookdir[0] / "reader_states.json").exists()


def test_unreadable_state_file_is_logged(app, client, tmp_bookdir, caplog):
    # a directory instead of the file
    (tmp_bookdir[0] / "reader_states.json").mkdir()
    response = client.get("/api/reader/state/doc-1")
    assert response.status_code == 500
    assert response.json["error"] == "Impossible de lire les états enregistrés."
    assert "Impossible de lire le fichier des états." in caplog.text


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

def test_move_reader_state(app, client):
    from app.api import move_reader_state

    client.put("/api/reader/state", json=dict(STATE, pageNumber=3))
    with app.test_request_context():
        move_reader_state("doc-1", "doc-2", page_offset=1)
        move_reader_state("unknown", "doc-3")
    assert client.get("/api/reader/state/doc-1").status_code == 404
    state = client.get("/api/reader/state/doc-2").json
    assert state["pageNumber"] == 4 and state["documentId"] == "doc-2"
    assert client.get("/api/reader/state/doc-3").status_code == 404
