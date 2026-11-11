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
