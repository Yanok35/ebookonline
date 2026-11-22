""" Indicators of the PDF files (srcs/pdfstats.py), book page and command line """

import json
from pathlib import Path

import pymupdf
import pytest

from srcs import pdfstats
from tests.conftest import make_pdf


def image_png(seed, size=64):
    """ A PNG image of noise (does not compress): about size² × 3 bytes """
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, size, size), False)
    pix.set_rect(pix.irect, (seed % 255, 0, 0))
    import random
    rng = random.Random(seed)
    for y in range(0, size, 4):
        for x in range(0, size, 4):
            pix.set_rect(pymupdf.IRect(x, y, x + 4, y + 4),
                         (rng.randrange(256), rng.randrange(256), rng.randrange(256)))
    return pix.tobytes("png")


def book_with_images(path, pages=3, shared=False):
    """ A page per image; shared: every page declares every image (as WeasyPrint does) """
    doc = pymupdf.open()
    for n in range(pages):
        page = doc.new_page(width=200, height=300)
        page.insert_text((20, 40), f"Page {n + 1}")
        page.insert_image(pymupdf.Rect(20, 60, 180, 220), stream=image_png(n))
    if shared:
        # one resource dictionary for every page, with every image; each
        # page draws its own image (by its name in this dictionary)
        images = [doc[n].get_images()[0][0] for n in range(pages)]
        font = doc.xref_get_key(doc[0].xref, "Resources/Font")[1]
        res = doc.get_new_xref()
        doc.update_object(res, f"<</Font {font}/XObject<<" + "".join(
            f"/Im{n} {x} 0 R" for n, x in enumerate(images)) + ">>>>")
        for n, page in enumerate(doc):
            for xref in page.get_contents():
                content = doc.xref_stream(xref).replace(b"/fzImg0 Do", f"/Im{n} Do".encode())
                doc.update_stream(xref, content)
            doc.xref_set_key(page.xref, "Resources", f"{res} 0 R")
    doc.save(path)
    return path


def test_measure(tmp_path):
    stats = pdfstats.measure(book_with_images(tmp_path / "a.pdf"))
    assert stats["file"]["pages"] == 3 and stats["file"]["size"] == (tmp_path / "a.pdf").stat().st_size
    assert stats["images"]["count"] == 3 and stats["images"]["bytes"] > 3 * 10000
    # (MuPDF writes the PNG images with an ICC profile)
    assert stats["images"]["colorspaces"] == {"ICC": 3}
    # each page declares its own image only
    assert stats["resources"]["max_images"] == 1
    assert stats["resources"]["max"] < stats["images"]["bytes"] / 2
    assert stats["bytes"]["images"] == stats["images"]["bytes"]
    assert pdfstats.warnings(stats) == []


def test_measure_shared_resources(tmp_path, monkeypatch):
    stats = pdfstats.measure(book_with_images(tmp_path / "a.pdf", pages=4, shared=True))
    res = stats["resources"]
    # every page declares the 4 images: their whole weight
    assert res["max_images"] == 4 and res["max"] == stats["images"]["bytes"]
    assert res["max_page"] == 1 and res["median"] == res["max"]
    monkeypatch.setattr(pdfstats, "SHARED_RESOURCES_BYTES", 1000)
    monkeypatch.setattr(pdfstats, "SHARED_RESOURCES_IMAGES", 2)
    stats = pdfstats.measure(tmp_path / "a.pdf")
    assert stats["resources"]["pages_over"] == 4
    [warning] = pdfstats.warnings(stats)
    assert warning.startswith("Ressources partagées : la page 1 déclare 4 images")


def test_measure_text_only(tmp_path):
    stats = pdfstats.measure(make_pdf(tmp_path / "a.pdf"))
    assert stats["images"]["count"] == 0 and stats["images"]["largest"] is None
    assert stats["resources"]["max_images"] == 0
    assert pdfstats.warnings(stats) == []


def test_measure_not_a_pdf(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"not a PDF file")
    stats = pdfstats.measure(tmp_path / "a.pdf")
    assert stats["error"].startswith("can not open the PDF file")
    assert pdfstats.warnings(stats) == []


@pytest.mark.parametrize("change, expected", [
    ({"images": {"cmyk": 2}}, "2 image(s) CMJN"),
    ({"images": {"jpx": 1}}, "1 image(s) JPEG 2000"),
    ({"images": {"max_pixels": 30_000_000}}, "Image très grande : 30 mégapixels"),
    ({"fonts": {"type3": 3}}, "3 police(s) Type 3"),
    ({"content": {"max": 2 * pdfstats.MB, "max_page": 7}}, "Page complexe : le contenu de la page 7"),
    ({"resources": {"max": 12 * pdfstats.MB, "max_page": 4, "max_images": 3}}, "Page lourde : la page 4"),
])
def test_warnings(tmp_path, change, expected):
    stats = pdfstats.measure(make_pdf(tmp_path / "a.pdf"))
    for part, values in change.items():
        stats[part].update(values)
    [warning] = pdfstats.warnings(stats)
    assert warning.startswith(expected)


def test_cache(tmp_path):
    pdf = book_with_images(tmp_path / "a.pdf")
    cache = tmp_path / "cache"
    cache.mkdir()
    assert pdfstats.read(cache, "0" * 40) is None
    entry = pdfstats.get(cache, "0" * 40, pdf)
    assert entry["sha1"] == "0" * 40 and entry["version"] == pdfstats.STATS_VERSION
    assert pdfstats.read(cache, "0" * 40) == entry
    # another version: measured again
    data = json.loads(Path(pdfstats.path(cache, "0" * 40)).read_text())
    Path(pdfstats.path(cache, "0" * 40)).write_text(json.dumps(dict(data, version=0)))
    assert pdfstats.read(cache, "0" * 40) is None
    # not writable: measured, not kept
    assert pdfstats.get(cache, "1" * 40, pdf, writable=False)["file"]["pages"] == 3
    assert pdfstats.read(cache, "1" * 40) is None
    # no file
    assert pdfstats.get(cache, "2" * 40, tmp_path / "missing.pdf") is None


# --- book page

@pytest.fixture
def book(app):
    book_with_images(Path(app.config["BOOK_DIR"]) / "Images.pdf")
    app.bookdir.rescan()
    return app.bookdir.find_book_by_filename("Images.pdf")


def test_book_page_section(app, client, book):
    html = client.get(f"/bookadmin/{book.sha1}").text
    # not measured yet: when opened
    assert f'data-src="/bookadmin/{book.sha1}/pdfstats">' in html and "Mesure du fichier…" in html
    fragment = client.get(f"/bookadmin/{book.sha1}/pdfstats").text
    assert 'data-warnings="0"' in fragment and "Aucun problème repéré." in fragment
    assert "<td>Taille, pages</td>" in fragment and "3 pages" in fragment
    # measured: in the page at once
    html = client.get(f"/bookadmin/{book.sha1}").text
    assert "data-loaded" in html and "Aucun problème repéré." in html
    assert Path(pdfstats.path(app.config["CACHE_DIR"], book.sha1)).exists()


def test_book_page_section_warnings(app, client, book, monkeypatch):
    monkeypatch.setattr(pdfstats, "COMPLEX_PAGE_BYTES", 10)
    fragment = client.get(f"/bookadmin/{book.sha1}/pdfstats").text
    assert 'data-warnings="1"' in fragment and "Page complexe" in fragment
    html = client.get(f"/bookadmin/{book.sha1}").text
    assert "Structure du PDF<span class=\"pdfstats-summary\"> — 1 alerte</span>" in html


def test_pdfstats_view_errors(app, client, book):
    assert client.get("/bookadmin/" + "0" * 40 + "/pdfstats").status_code == 404
    assert app.test_client().get(f"/bookadmin/{book.sha1}/pdfstats").status_code == 302
    (Path(app.config["BOOK_DIR"]) / "Images.pdf").unlink()
    app.bookdir.rescan()
    assert "Le PDF est absent" in client.get(f"/bookadmin/{book.sha1}/pdfstats").text
    assert 'id="pdfstats"' not in client.get(f"/bookadmin/{book.sha1}").text


# --- command line

def pdf_cli(app, *args):
    from tests.conftest import invoke_cli

    return invoke_cli(app, "pdf", *args)


def test_audit(app, book):
    book_with_images(Path(app.config["BOOK_DIR"]) / "Shared.pdf", pages=4, shared=True)
    (Path(app.config["BOOK_DIR"]) / "bad.pdf").write_bytes(b"not a PDF file")
    result = pdf_cli(app, "audit")
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    # the heaviest first
    books = [line.split()[-1] for line in lines if line.endswith(".pdf")]
    assert books == ["Shared.pdf", "Images.pdf"]
    assert "2 file(s) measured, 0 with warnings, 1 unreadable" in result.output
    assert "error  bad.pdf: can not open the PDF file" in result.output
    # cached
    assert pdfstats.read(app.config["CACHE_DIR"], book.sha1) is not None
    result = pdf_cli(app, "audit", "--warnings")
    assert [line for line in result.output.splitlines() if line.endswith(".pdf")] == []


def test_audit_in_parallel(app, book):
    result = pdf_cli(app, "audit", "-j", "2", "Images.pdf")
    assert result.exit_code == 0, result.output
    assert "1 file(s) measured" in result.output


def test_show(app, book):
    result = pdf_cli(app, "show", "Images.pdf")
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[0] == "Images.pdf"
    assert "3 pages" in result.output and "images    3," in result.output
    data = json.loads(pdf_cli(app, "show", book.sha1, "--json").output)
    assert data["file"]["pages"] == 3 and data["warnings"] == []
    assert pdf_cli(app, "show", "unknown.pdf").exit_code == 2


# --- optimization from the book page

def test_optimize_from_the_book_page(app, client, monkeypatch):
    import re

    root = Path(app.config["BOOK_DIR"])
    book_with_images(root / "Shared.pdf", pages=4, shared=True)
    app.bookdir.rescan()
    book = app.bookdir.find_book_by_filename("Shared.pdf")
    old_sha1 = book.sha1
    client.put("/api/reader/state", json={"documentId": old_sha1, "documentName": "Shared.pdf",
                                          "pageNumber": 3, "positionX": 0, "positionY": 0, "zoom": 1})
    # no button: under the threshold
    assert 'value="Optimiser le PDF"' not in client.get(f"/bookadmin/{old_sha1}/pdfstats").text
    # the threshold: between the original and the optimized file (a page
    # then declares a quarter of the resources)
    heaviest = pdfstats.measure(root / "Shared.pdf")["resources"]["max"]
    monkeypatch.setattr(pdfstats, "SHARED_RESOURCES_BYTES", heaviest // 2)
    fragment = client.get(f"/bookadmin/{old_sha1}/pdfstats").text
    assert 'value="Optimiser le PDF"' in fragment
    csrf = re.search(r'name="optimize-csrf_token" type="hidden" value="([^"]+)"', fragment).group(1)

    response = client.post(f"/bookadmin/{old_sha1}/optimize", data={"optimize-csrf_token": csrf})
    assert book.sha1 != old_sha1
    assert response.status_code == 302 and response.location == f"/bookadmin/{book.sha1}"
    html = client.get(response.location).text
    assert "PDF optimisé : la page la plus lourde déclarait" in html
    assert "L&#39;original est dans la corbeille : Trash/Shared (original).pdf" in html
    # the position: same page
    assert client.get(f"/api/reader/state/{book.sha1}").json["pageNumber"] == 3
    # once optimized: no more button
    assert 'value="Optimiser le PDF"' not in client.get(f"/bookadmin/{book.sha1}/pdfstats").text


def test_optimize_refused_from_the_book_page(app, client):
    import re

    make_pdf(Path(app.config["BOOK_DIR"]) / "Text.pdf")
    app.bookdir.rescan()
    book = app.bookdir.find_book_by_filename("Text.pdf")
    page = f"/bookadmin/{book.sha1}"
    response = client.post(f"{page}/optimize", data={})
    assert "Formulaire expiré ou invalide" in client.get(response.location).text
    # (any form of the page: the same CSRF token)
    token = re.search(r'name="cover-csrf_token" type="hidden" value="([^"]+)"', client.get(page).text).group(1)
    response = client.post(f"{page}/optimize", data={"optimize-csrf_token": token})
    # no resources: nothing to gain
    assert "Opération refusée : resources per page: nothing to gain" in client.get(response.location).text
