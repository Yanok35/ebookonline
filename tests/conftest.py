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

    def create_thumbnail(self, pdffilename, sha1):
        self.requests.append((pdffilename, sha1))

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
    FakeCache and without the watcher.
    """
    from app import create_app

    tmp_path, bookdir, cachedir = tmp_bookdir
    for name, value in {
        "SECRET_KEY": "test",
        "BOOK_DIR": str(bookdir),
        "BOOK_DB": str(tmp_path / "book.db"),
        "CACHE_DIR": str(cachedir),
        "BOOK_DIR_WATCH": "false",
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
