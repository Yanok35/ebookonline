""" Timeline of the books of interest (app/timeline.py) """

import datetime
import json
import re
from pathlib import Path

from tests.conftest import make_pdf


def history(html):
    return json.loads(re.search(r"var HISTORY = (.*);\n", html).group(1))


def journal(app, events):
    with open(app.config["READER_EVENTS_FILE"], "w") as f:
        for minutes, doc, user in events:
            t = datetime.datetime(2026, 11, 1, 20, 0, tzinfo=datetime.UTC) + datetime.timedelta(minutes=minutes)
            f.write(json.dumps({"t": t.isoformat(), "doc": doc, "page": 1, "user": user}) + "\n")


def library(app):
    root = Path(app.config["BOOK_DIR"])
    for name in ("a", "b"):
        make_pdf(root / f"{name}.pdf")
    app.bookdir.rescan()
    return {Path(b.filename).stem: b for b in app.bookdir.get_all_books()}


def test_timeline_of_the_user(app, client):
    books = library(app)
    a, b = books["a"].sha1, books["b"].sha1
    journal(app, [(0, a, "test"), (5, a, "test"), (60, a, "test"),
                  (2, b, "other"),              # another user
                  (3, "0" * 40, "test")])        # not in the library
    html = client.get("/timeline").text
    found = history(html)
    assert [h["sha1"] for h in found] == [a]
    assert found[0]["name"] == "a" and found[0]["url"] == f"/reader/{a}"
    assert [s["minutes"] for s in found[0]["sessions"]] == [6.0, 1.0]
    assert found[0]["sessions"][0]["start"].startswith("2026-11-01T20:00:00")


def test_missing_book_is_left_out(app, client):
    books = library(app)
    journal(app, [(0, books["a"].sha1, "test")])
    (Path(app.config["BOOK_DIR"]) / "a.pdf").unlink()
    app.bookdir.rescan()
    assert "Aucune lecture enregistrée" in client.get("/timeline").text


def test_empty_timeline(app, client):
    assert "Aucune lecture enregistrée" in client.get("/timeline").text
    app.config["READER_EVENTS_FILE"] = ""
    assert "Le journal des lectures est désactivé" in client.get("/timeline").text


def test_timeline_requires_login(app):
    assert app.test_client().get("/timeline").status_code == 302


def test_library_links_to_the_timeline(client):
    assert 'href="/timeline">Mes lectures</a>' in client.get("/browser_lazy").text


def test_the_cover_opens_the_book_under_the_caption(app, client):
    """
    With a mouse, the caption is a bubble next to the cover, not over it,
    and it lets the clicks through, as the badge of the reading time does
    """
    books = library(app)
    journal(app, [(0, books["a"].sha1, "test")])
    style = re.search(r"<style>(.*?)</style>", client.get("/timeline").text, re.S).group(1)
    hover = re.search(r"@media \(hover: hover\) \{(.*)\}", style, re.S).group(1)
    caption = re.search(r"\.timeline \.simple-caption,\s*\.timeline \.book-box:hover \.simple-caption \{([^}]*)\}",
                        hover).group(1)
    assert "pointer-events: none" in caption
    assert "top: 100%" in caption and "translateX(-50%)" in caption
    badge = re.search(r"\.timeline \.reading-time \{([^}]*)\}", style).group(1)
    assert "pointer-events: none" in badge
