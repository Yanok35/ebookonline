""" Reading history: sessions from the journal of the reader events (srcs/history.py) """

import datetime
import json

from srcs.history import SESSION_GAP, SESSION_TAIL, read_events, reading_sessions, sessions

T = datetime.datetime(2026, 11, 1, 20, 0, tzinfo=datetime.UTC)


def at(minutes):
    return T + datetime.timedelta(minutes=minutes)


def write(path, events):
    path.write_text("".join(json.dumps(e) + "\n" for e in events))


def event(minutes, doc="a", user="alice", page=1):
    return {"t": at(minutes).isoformat(timespec="seconds"), "doc": doc, "page": page, "user": user}


def test_sessions():
    events = [(at(0), "a"), (at(3), "a"), (at(9), "a"),   # a: 9 min
              (at(5), "b"),                               # b: alone
              (at(30), "a"), (at(31), "a")]               # a: again, after a gap
    events.sort()
    tail = SESSION_TAIL.total_seconds() / 60
    assert sessions(events) == {
        "a": [(at(0), 9 + tail), (at(30), 1 + tail)],
        "b": [(at(5), tail)],
    }


def test_session_gap():
    gap = SESSION_GAP.total_seconds() / 60
    assert len(sessions([(at(0), "a"), (at(gap), "a")])["a"]) == 1
    assert len(sessions([(at(0), "a"), (at(gap + 1), "a")])["a"]) == 2


def test_read_events(tmp_path, caplog):
    path = tmp_path / "events.jsonl"
    write(path, [event(5), event(0, doc="b"), event(1, user="bob")])
    with open(path, "a") as f:
        f.write('{"t": "2026-11-01T20:0')  # truncated by a crash
        f.write("\n" + json.dumps({"doc": "a"}) + "\n")
    assert read_events(path, "alice") == [(at(0), "b"), (at(5), "a")]
    assert len(read_events(path)) == 3
    assert caplog.text.count("malformed, skipped") == 4


def test_time_without_timezone_is_utc(tmp_path):
    path = tmp_path / "events.jsonl"
    write(path, [event(5), dict(event(0), t="2026-11-01T20:00:00")])
    assert read_events(path) == [(at(0), "a"), (at(5), "a")]


def test_missing_journal(tmp_path):
    assert reading_sessions(tmp_path / "missing.jsonl", "alice") == {}


def test_reading_sessions(tmp_path):
    path = tmp_path / "events.jsonl"
    write(path, [event(0), event(4), event(2, doc="b"), event(1, user="bob")])
    found = reading_sessions(path, "alice")
    assert sorted(found) == ["a", "b"] and found["a"][0][0] == at(0)
