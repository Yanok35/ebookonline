import os
import time

import pytest

from pypdf import PdfWriter

from srcs.book import BookDir
from srcs.cache import Cache


class FakeCache(Cache):
    """
    Cache without the thumbnail process pool: thumbnail requests are only
    recorded, as (pdf path, sha1) tuples.
    """

    def __init__(self, cachedir):
        self.cachedir = str(cachedir)
        self.subproc = []
        self.requests = []
        # backend of each request (None: each one in turn)
        self.backends = []

    def _queue_thumbnail(self, pdffilename, thumbname, backend=None):
        sha1 = os.path.splitext(os.path.basename(thumbname))[0]
        self.requests.append((pdffilename, sha1))
        self.backends.append(backend)

    def __del__(self):
        pass


def make_pdf(path, title=None):
    """
    Write a small valid PDF. The title makes its content (thus its sha1)
    unique; it defaults to the file name.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=210, height=297)
    writer.add_metadata({"/Title": title or path.name})
    with open(path, "wb") as f:
        writer.write(f)
    return path


def make_book_pdf(path, pages, metadata=None, xmp=None):
    """
    Write a PDF file with text (PyMuPDF), for the metadata analysis: pages
    is a list of pages, each one a list of (font size, line of text).
    metadata: Info dictionary, e.g. {"title": ..., "author": ...}; xmp: XMP
    metadata (XML string).
    """
    import pymupdf

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page(width=420, height=595)
        y = 60
        for size, text in lines:
            page.insert_text((30, y), text, fontsize=size)
            y += size + 8
    if metadata:
        doc.set_metadata(metadata)
    if xmp:
        doc.set_xml_metadata(xmp)
    doc.save(path)
    doc.close()
    return path


def wait_until(predicate, timeout=5.0, interval=0.05):
    """ Poll predicate() until it is true, or fail after timeout seconds """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture
def tmp_bookdir(tmp_path):
    """ (test directory, book directory, cache directory) """
    bookdir = tmp_path / "books"
    cachedir = tmp_path / "cache"
    bookdir.mkdir()
    cachedir.mkdir()
    return tmp_path, bookdir, cachedir


@pytest.fixture
def library(tmp_bookdir):
    """ A BookDir on an empty temporary book directory, with a FakeCache """
    tmp_path, bookdir, cachedir = tmp_bookdir
    cache = FakeCache(cachedir)
    d = BookDir(str(tmp_path / "book.db"), cache)
    d.open(str(bookdir))
    return d


@pytest.fixture
def app(tmp_bookdir, monkeypatch):
    """
    The Flask application on an empty temporary book directory, with a
    FakeCache, without the watcher and the metadata analysis.
    """
    from app import create_app

    tmp_path, bookdir, cachedir = tmp_bookdir
    for name, value in {
        "SECRET_KEY": "test",
        "BOOK_DIR": str(bookdir),
        "BOOK_DB": str(tmp_path / "book.db"),
        "STATE_FILE": str(tmp_path / "reader_states.json"),
        "CACHE_DIR": str(cachedir),
        "BOOK_DIR_WATCH": "false",
        "METADATA_ANALYSIS": "false",
    }.items():
        monkeypatch.setenv("EBOOKONLINE_" + name, value)
    monkeypatch.setattr(Cache, "get_instance",
                        classmethod(lambda cls, cachedir: FakeCache(cachedir)))

    app = create_app("default")
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """ A test client with a logged in user """
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "test"
    return client
