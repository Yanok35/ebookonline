"""
Suggestions of metadata on the book page (app/admin/metadata.py), from the
metadata cache files (srcs/metadata).
"""

import json
import re
from pathlib import Path

import pytest

from srcs.metadata import analyse, extract, store
from tests.conftest import make_pdf
from tests.unittests.test_admin import csrf_token


@pytest.fixture
def book(app):
    make_pdf(Path(app.config["BOOK_DIR"]) / "nutshell.pdf")
    app.bookdir.rescan()
    return app.bookdir.find_book_by_filename("nutshell.pdf")


def write_analysis(app, book, candidates, **raw):
    store.write(app.config["CACHE_DIR"], {
        "sha1": book.sha1, "extract_version": extract.EXTRACT_VERSION,
        "analyser_version": analyse.ANALYSER_VERSION,
        "extracted_at": "2026-11-14T17:52:00+00:00", "analysed_at": "2026-11-14T17:52:00+00:00",
        "error": None, "raw": {"has_text": True, "texts": {"0": "Python in a Nutshell"}, **raw},
        "candidates": candidates,
    })


CANDIDATES = {
    "title": [["Python in a Nutshell", "xmp", 50]],
    "authors": [["Alex Martelli", "title-page", 50], ["Anna Ravenscroft", "title-page", 50],
                ["Steve Holden", "isolated-name", 8]],
    "editor": [["O'Reilly", "text-publisher", 45]],
    "year": [[2006, "copyright", 50]],
    "isbn": [["9780596100469", "isbn", 55]],
}


def field_tag(html, name):
    """ The input (or textarea) tag of a field of the book form """
    m = re.search(rf'<(input|textarea)[^>]*\bname="{name}"[^>]*>', html)
    return m.group(0)


def test_empty_fields_are_prefilled(app, client, book):
    write_analysis(app, book, CANDIDATES)
    html = client.get(f"/bookadmin/{book.sha1}").text
    for name, value in [("title", "Python in a Nutshell"), ("editor", "O&#39;Reilly"),
                        ("year", "2006"), ("isbn", "9780596100469")]:
        tag = field_tag(html, name)
        assert f'value="{value}"' in tag and 'class="suggested"' in tag
    assert 'class="suggested"' in field_tag(html, "authors")
    assert re.search(r'name="authors"[^>]*>\s*Alex Martelli\nAnna Ravenscroft</textarea>', html)
    assert "Suggestion (score 50/100 : métadonnées XMP)." in html
    # another name found, to add
    assert 'data-value="Steve Holden"' in html
    # the tags are not analysed
    assert 'class="suggested"' not in field_tag(html, "tags")
    # nothing is saved by showing the page
    assert (book.title, book.authors, book.editor) == ("", [], "")


def test_user_values_are_not_replaced(app, client, book):
    book.title, book.editor, book.year = "Python in a nutshell", "O'Reilly Media", 2007
    write_analysis(app, book, CANDIDATES)
    html = client.get(f"/bookadmin/{book.sha1}").text
    assert 'value="Python in a nutshell"' in field_tag(html, "title")
    assert 'class="suggested"' not in field_tag(html, "title")
    # same title (case), same publisher (alias): no hint; another year: hint
    assert "Suggestion : <q>Python in a Nutshell</q>" not in html
    assert "Suggestion : <q>O&#39;Reilly</q>" not in html
    assert "Suggestion : <q>2006</q>" in html
    assert re.search(r'data-field="year"\s+data-value="2006"', html)


def test_reviewed_book_is_not_prefilled(app, client, book):
    book.meta_reviewed = True
    write_analysis(app, book, CANDIDATES)
    html = client.get(f"/bookadmin/{book.sha1}").text
    assert 'class="suggested"' not in html
    assert 'class="badge reviewed">relu<' in html
    # shown as hints, the field stays empty
    assert "Suggestion : <q>2006</q>" in html
    assert 'value=""' in field_tag(html, "year")
    assert 'value="Enregistrer et remettre à relire"' in html


def test_save_title_and_authors(app, client, book):
    url = f"/bookadmin/{book.sha1}"
    response = client.post(url, data={
        "csrf_token": csrf_token(client, url),
        "title": " Python in a Nutshell ",
        "subtitle": " A Desktop Quick Reference ",
        "authors": "Alex Martelli\n\n  Anna   Ravenscroft ; Steve Holden",
        "editor": "O'Reilly", "year": "2006", "isbn": "", "tags": "",
    })
    assert response.status_code == 302
    assert book.title == "Python in a Nutshell"
    assert book.subtitle == "A Desktop Quick Reference"
    assert book.authors == ["Alex Martelli", "Anna Ravenscroft", "Steve Holden"]
    assert book.meta_reviewed is False
    with open(app.config["BOOK_DB"]) as f:
        entry = next(b for b in json.load(f)["booklist"] if b["sha1"] == book.sha1)
    assert entry["authors"] == book.authors and entry["title"] == book.title
    assert entry["subtitle"] == book.subtitle


def test_subtitle_is_prefilled(app, client, book):
    write_analysis(app, book, dict(CANDIDATES, title=[
        ["Python in a Nutshell: A Desktop Quick Reference", "xmp", 50],
        ["Python in a Nutshell", "title-page", 50]]))
    html = client.get(f"/bookadmin/{book.sha1}").text
    assert 'value="Python in a Nutshell"' in field_tag(html, "title")
    tag = field_tag(html, "subtitle")
    assert 'value="A Desktop Quick Reference"' in tag and 'class="suggested"' in tag


def test_save_and_mark_as_reviewed(app, client, book):
    url = f"/bookadmin/{book.sha1}"
    data = {"title": "T", "authors": "", "editor": "", "year": "", "isbn": "", "tags": ""}
    client.post(url, data={"csrf_token": csrf_token(client, url), "review": "1", **data})
    assert book.meta_reviewed is True
    assert "métadonnées marquées comme relues" in client.get(url).text

    client.post(url, data={"csrf_token": csrf_token(client, url), "unreview": "1", **data})
    assert book.meta_reviewed is False
    # a plain save keeps the state
    book.meta_reviewed = True
    client.post(url, data={"csrf_token": csrf_token(client, url), **data})
    assert book.meta_reviewed is True


def test_invalid_authors(client, book):
    url = f"/bookadmin/{book.sha1}"
    response = client.post(url, data={"csrf_token": csrf_token(client, url),
                                      "authors": "x" * 201, "title": "", "tags": ""})
    assert response.status_code == 200
    assert "200 caractères au plus par auteur." in response.text
    assert book.authors == []


def test_rejected_form_is_not_prefilled(app, client, book):
    write_analysis(app, book, CANDIDATES)
    url = f"/bookadmin/{book.sha1}"
    html = client.post(url, data={"csrf_token": csrf_token(client, url),
                                  "title": "", "year": "abc"}).text
    # the user input is shown, not the suggestions
    assert 'value="abc"' in field_tag(html, "year")
    assert 'class="suggested"' not in html


def test_learned_editor_spelling(app, client, book):
    make_pdf(Path(app.config["BOOK_DIR"]) / "other.pdf")
    app.bookdir.rescan()
    app.bookdir.find_book_by_filename("other.pdf").editor = "O'Reilly Media"
    write_analysis(app, book, CANDIDATES)
    html = client.get(f"/bookadmin/{book.sha1}").text
    assert 'value="O&#39;Reilly Media"' in field_tag(html, "editor")


def test_analysis_state_and_detail(app, client, book):
    url = f"/bookadmin/{book.sha1}"
    assert "PDF non analysé." in client.get(url).text
    assert "Détail de l'analyse" not in client.get(url).text

    write_analysis(app, book, CANDIDATES, has_text=False)
    html = client.get(url).text
    assert "PDF analysé le 2026-11-14 17:52 (UTC)." in html
    assert "Peu ou pas de texte" in html
    assert "Détail de l'analyse" in html
    assert "<td>page de titre</td><td>Alex Martelli</td>" in html
    assert "<h4>Page 1</h4>" in html and "<pre>Python in a Nutshell</pre>" in html

    store.write_error(app.config["CACHE_DIR"], book.sha1, "can not open the PDF file")
    html = client.get(url).text
    assert "Échec de l&#39;analyse : can not open the PDF file" in html
    assert 'class="suggested"' not in html


def analyse_csrf_token(client, book):
    html = client.get(f"/bookadmin/{book.sha1}").text
    return re.search(r'name="analyse-csrf_token" type="hidden" value="([^"]+)"', html).group(1)


def test_analyse_again(app, client, book, mocker):
    # the service is not started by the tests (METADATA_ANALYSIS false)
    url = f"/bookadmin/{book.sha1}/analyse"
    token = analyse_csrf_token(client, book)
    client.post(url, data={"analyse-csrf_token": token})
    assert "L&#39;analyse des PDF est désactivée" in client.get(f"/bookadmin/{book.sha1}").text

    mocker.patch.object(type(app.metadata), "running", new=True)
    request = mocker.patch.object(app.metadata, "request")
    response = client.post(url, data={"analyse-csrf_token": analyse_csrf_token(client, book)})
    assert response.status_code == 302
    request.assert_called_once_with(book.sha1, str(Path(app.config["BOOK_DIR"]) / "nutshell.pdf"),
                                    urgent=True, force=True)
    assert "Analyse demandée" in client.get(f"/bookadmin/{book.sha1}").text


def test_analyse_requires_csrf_token(app, client, book, mocker):
    mocker.patch.object(type(app.metadata), "running", new=True)
    request = mocker.patch.object(app.metadata, "request")
    client.post(f"/bookadmin/{book.sha1}/analyse")
    assert request.call_count == 0


def test_pending_analysis(app, client, book, mocker):
    mocker.patch.object(app.metadata, "is_pending", return_value=True)
    html = client.get(f"/bookadmin/{book.sha1}").text
    assert "Analyse en cours…" in html
    assert f'data-poll="/bookadmin/{book.sha1}/analysis"' in html
    assert client.get(f"/bookadmin/{book.sha1}/analysis").json == {"pending": True}


def test_analysis_state_requires_login(app, book):
    assert app.test_client().get(f"/bookadmin/{book.sha1}/analysis").status_code == 302
    assert app.test_client().post(f"/bookadmin/{book.sha1}/analyse").status_code == 302
