import os
from pathlib import Path

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
