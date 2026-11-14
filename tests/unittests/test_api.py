import json

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
