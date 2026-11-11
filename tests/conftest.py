import pytest


@pytest.fixture
def tmp_bookdir(tmp_path):
    """ (test directory, book directory, cache directory) """
    bookdir = tmp_path / "books"
    cachedir = tmp_path / "cache"
    bookdir.mkdir()
    cachedir.mkdir()
    return tmp_path, bookdir, cachedir
