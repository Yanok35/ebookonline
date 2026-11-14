""" Cache files of the metadata (srcs/metadata/store.py) """

import gzip
import json
import os

import pytest

from srcs.metadata import analyse, extract, store
from tests.conftest import make_book_pdf

SHA1 = "a" * 40


@pytest.fixture
def book_pdf(tmp_path):
    return make_book_pdf(tmp_path / "book.pdf", [
        [(28, "Les Misérables"), (12, "Victor Hugo")],
        [(9, "Dépôt légal : mars 2012")]], metadata={"producer": "test"})


@pytest.fixture
def cache_dir(tmp_path):
    d = tmp_path / "cache"
    d.mkdir()
    return str(d)


def test_update_extracts_then_is_current(cache_dir, book_pdf, mocker):
    assert store.update(cache_dir, SHA1, str(book_pdf)) == store.EXTRACTED
    entry = store.read(cache_dir, SHA1)
    assert entry["sha1"] == SHA1 and entry["error"] is None
    assert entry["extract_version"] == extract.EXTRACT_VERSION
    assert entry["analyser_version"] == analyse.ANALYSER_VERSION
    assert entry["raw"]["pages"] == 2
    assert [2012, "legal-deposit", 75] in entry["candidates"]["year"]
    # a gzip compressed JSON file, nothing else left in the directory
    with gzip.open(os.path.join(cache_dir, SHA1 + ".meta.json.gz"), "rt") as f:
        assert json.load(f) == entry
    assert os.listdir(cache_dir) == [SHA1 + ".meta.json.gz"]

    spy = mocker.spy(extract, "extract")
    assert store.update(cache_dir, SHA1, str(book_pdf)) == store.CURRENT
    assert spy.call_count == 0


def test_new_analyser_version_does_not_open_the_pdf(cache_dir, book_pdf, mocker):
    store.update(cache_dir, SHA1, str(book_pdf))
    mocker.patch.object(analyse, "ANALYSER_VERSION", analyse.ANALYSER_VERSION + 1)
    spy = mocker.spy(extract, "extract")
    os.unlink(book_pdf)

    assert store.update(cache_dir, SHA1, str(book_pdf)) == store.ANALYSED
    assert spy.call_count == 0
    assert store.read(cache_dir, SHA1)["analyser_version"] == analyse.ANALYSER_VERSION


def test_new_extract_version_opens_the_pdf(cache_dir, book_pdf, mocker):
    store.update(cache_dir, SHA1, str(book_pdf))
    mocker.patch.object(extract, "EXTRACT_VERSION", extract.EXTRACT_VERSION + 1)
    assert store.update(cache_dir, SHA1, str(book_pdf)) == store.EXTRACTED
    assert store.read(cache_dir, SHA1)["extract_version"] == extract.EXTRACT_VERSION


def test_force_opens_the_pdf(cache_dir, book_pdf):
    store.update(cache_dir, SHA1, str(book_pdf))
    assert store.update(cache_dir, SHA1, str(book_pdf), force=True) == store.EXTRACTED


def test_unreadable_pdf_is_saved_as_failed(cache_dir, tmp_path, mocker):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a PDF file")
    assert store.update(cache_dir, SHA1, str(bad)) == store.FAILED
    entry = store.read(cache_dir, SHA1)
    assert entry["error"].startswith("can not open the PDF file")
    assert entry["candidates"] == {}
    # not tried again, even with new rules
    mocker.patch.object(analyse, "ANALYSER_VERSION", analyse.ANALYSER_VERSION + 1)
    assert store.update(cache_dir, SHA1, str(bad)) == store.CURRENT


def test_missing_pdf_writes_nothing(cache_dir, tmp_path):
    assert store.update(cache_dir, SHA1, str(tmp_path / "missing.pdf")) == store.MISSING
    assert os.listdir(cache_dir) == []


def test_read(cache_dir):
    assert store.read(cache_dir, SHA1) is None
    with open(store.path(cache_dir, SHA1), "wb") as f:
        f.write(b"garbage")
    assert store.read(cache_dir, SHA1) is None


def test_internal_error_is_tried_again(cache_dir, book_pdf):
    """ An unexpected exception (a bug) is tried again; a damaged PDF file is not """
    store.write_error(cache_dir, SHA1, store.INTERNAL_ERROR + "FzErrorFormat: code=7: object is not a stream")
    assert store.is_internal_error(store.read(cache_dir, SHA1))
    assert store.update(cache_dir, SHA1, str(book_pdf)) == store.EXTRACTED
    assert store.read(cache_dir, SHA1)["error"] is None

    store.write_error(cache_dir, SHA1, "can not open the PDF file: broken")
    assert store.update(cache_dir, SHA1, str(book_pdf)) == store.CURRENT
