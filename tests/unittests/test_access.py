import os

import pytest

from srcs.access import can_write_dir, check_write_access

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
                              tmp_path / "reader_states.json") == []
    # relative paths: in the current directory
    monkeypatch.chdir(tmp_path)
    assert check_write_access(".", "book.db", "reader_states.json") == []


@needs_non_root
def test_check_write_access_problems(tmp_path, read_only_dir):
    problems = check_write_access(read_only_dir, tmp_path / "book.db",
                                  read_only_dir / "reader_states.json")
    assert problems == [
        f"Écriture impossible dans le répertoire des livres : {read_only_dir}",
        "Écriture impossible dans le répertoire des positions de lecture "
        f"(reader_states.json) : {read_only_dir}",
    ]

    problems = check_write_access(tmp_path, read_only_dir / "book.db",
                                  tmp_path / "reader_states.json")
    assert problems == ["Écriture impossible dans le répertoire de la base "
                        f"des livres (book.db) : {read_only_dir}"]
