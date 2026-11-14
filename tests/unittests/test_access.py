import os

import pytest

from srcs.access import can_read_dir, can_write_dir, check_write_access

# root writes in read-only directories
needs_non_root = pytest.mark.skipif(os.geteuid() == 0, reason="run as root")


@pytest.fixture
def read_only_dir(tmp_path):
    d = tmp_path / "read-only"
    d.mkdir()
    d.chmod(0o555)
    yield d
    d.chmod(0o755)


def test_can_write_dir(tmp_path):
    assert can_write_dir(tmp_path)
    # the test file is removed
    assert list(tmp_path.iterdir()) == []
    assert not can_write_dir(tmp_path / "missing")


@needs_non_root
def test_can_not_write_dir(read_only_dir):
    assert not can_write_dir(read_only_dir)


def test_check_write_access(tmp_path, monkeypatch):
    assert check_write_access(tmp_path, tmp_path / "book.db",
                              tmp_path / "reader_states.json", tmp_path) == []
    # relative paths: in the current directory
    monkeypatch.chdir(tmp_path)
    assert check_write_access(".", "book.db", "reader_states.json", ".") == []


@needs_non_root
def test_check_write_access_problems(tmp_path, read_only_dir):
    problems = check_write_access(read_only_dir, tmp_path / "book.db",
                                  read_only_dir / "reader_states.json", tmp_path)
    assert problems == [
        f"Écriture impossible dans le répertoire des livres : {read_only_dir}",
        "Écriture impossible dans le répertoire des positions de lecture "
        f"(reader_states.json) : {read_only_dir}",
    ]

    problems = check_write_access(tmp_path, read_only_dir / "book.db",
                                  tmp_path / "reader_states.json", tmp_path)
    assert problems == ["Écriture impossible dans le répertoire de la base "
                        f"des livres (book.db) : {read_only_dir}"]


def test_can_read_dir(tmp_path):
    assert can_read_dir(tmp_path)
    assert not can_read_dir(tmp_path / "missing")
    (tmp_path / "file").touch()
    assert not can_read_dir(tmp_path / "file")


@needs_non_root
def test_thumbnail_cache_access(tmp_path, read_only_dir):
    def problems(cache_dir):
        return check_write_access(tmp_path, tmp_path / "book.db",
                                  tmp_path / "reader_states.json", cache_dir)

    assert problems(read_only_dir) == [
        f"Écriture impossible dans le répertoire des miniatures : {read_only_dir}"]

    unreadable = tmp_path / "unreadable"
    unreadable.mkdir()
    unreadable.chmod(0o300)
    try:
        assert problems(unreadable) == [
            f"Lecture impossible dans le répertoire des miniatures : {unreadable}"]
    finally:
        unreadable.chmod(0o755)

    assert problems(tmp_path / "missing") == [
        f"Lecture impossible dans le répertoire des miniatures : {tmp_path / 'missing'}",
        f"Écriture impossible dans le répertoire des miniatures : {tmp_path / 'missing'}"]
