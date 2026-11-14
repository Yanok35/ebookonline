import os
import shutil
import time
from pathlib import Path

import pytest

import srcs.book
from srcs.book import BookDir
from srcs.watcher import BookDirWatcher

from tests.conftest import FakeCache, make_pdf, wait_until

DELAY = 0.2


@pytest.fixture
def watched(library):
    """ A started watcher on the library, counting the rescans it triggers """
    library.rescan()

    rescans = []
    original = library.rescan

    def counting_rescan():
        rescans.append(time.monotonic())
        return original()

    library.rescan = counting_rescan

    watcher = BookDirWatcher(library, delay=DELAY)
    watcher.start()
    yield library, rescans
    watcher.stop()


def present_names(library):
    return sorted(b.filename for b in library.get_booklist())


def test_new_pdf_is_added(watched):
    library, rescans = watched
    root = Path(library.dirpath)

    make_pdf(root / "new.pdf")

    assert wait_until(lambda: present_names(library) == ["new.pdf"])
    assert library.cache.requests[-1][0] == str(root / "new.pdf")


def test_burst_of_events_triggers_a_single_rescan(watched):
    library, rescans = watched
    root = Path(library.dirpath)

    for i in range(5):
        make_pdf(root / f"book{i}.pdf")

    assert wait_until(lambda: len(present_names(library)) == 5)
    time.sleep(DELAY * 3)
    assert len(rescans) == 1


def test_moved_directory(watched):
    library, rescans = watched
    root = Path(library.dirpath)
    make_pdf(root / "Old" / "a.pdf")
    assert wait_until(lambda: present_names(library) == ["Old/a.pdf"])
    book = library.get_booklist()[0]
    book.bookmarked = True

    shutil.move(root / "Old", root / "New")

    assert wait_until(lambda: present_names(library) == ["New/a.pdf"])
    assert book.category == "New" and book.bookmarked


def test_deleted_pdf_is_hidden(watched):
    library, rescans = watched
    root = Path(library.dirpath)
    make_pdf(root / "a.pdf")
    make_pdf(root / "b.pdf")
    assert wait_until(lambda: len(present_names(library)) == 2)

    os.remove(root / "a.pdf")

    assert wait_until(lambda: present_names(library) == ["b.pdf"])
    assert library.find_book_by_filename("a.pdf") is not None


def test_non_pdf_files_are_ignored(watched):
    library, rescans = watched
    root = Path(library.dirpath)

    (root / "notes.txt").write_text("hello")
    (root / "notes.txt").rename(root / "notes.md")

    time.sleep(DELAY * 4)
    assert rescans == []


def test_symlinked_book_dir(tmp_path):
    """ BOOK_DIR may be a symbolic link to the real library directory """
    real = tmp_path / "library"
    real.mkdir()
    link = tmp_path / "books"
    link.symlink_to(real)
    library = BookDir(str(tmp_path / "book.db"), FakeCache(tmp_path / "cache"))
    library.open(str(link))
    library.rescan()

    watcher = BookDirWatcher(library, delay=DELAY)
    watcher.start()
    try:
        # added in the target directory, at its root and in a subdirectory
        make_pdf(real / "root.pdf")
        make_pdf(real / "Science" / "sub.pdf")
        assert wait_until(
            lambda: present_names(library) == ["Science/sub.pdf", "root.pdf"])

        os.remove(real / "root.pdf")
        assert wait_until(lambda: present_names(library) == ["Science/sub.pdf"])
    finally:
        watcher.stop()


def test_stop_cancels_pending_rescan(library):
    root = Path(library.dirpath)
    watcher = BookDirWatcher(library, delay=1.0)
    watcher.start()
    make_pdf(root / "a.pdf")
    time.sleep(0.2)  # event received, rescan pending
    watcher.stop()

    time.sleep(1.2)
    assert present_names(library) == []


def test_file_operations_are_not_undone(watched, mocker):
    library, rescans = watched
    root = Path(library.dirpath)
    make_pdf(root / "a.pdf")
    make_pdf(root / "b.pdf")
    assert wait_until(lambda: present_names(library) == ["a.pdf", "b.pdf"])
    a = library.find_book_by_filename("a.pdf")
    b = library.find_book_by_filename("b.pdf")
    time.sleep(DELAY * 3)
    count = len(rescans)
    spy = mocker.spy(srcs.book, "sha1_file")

    library.move_book(a.sha1, "Art/a.pdf")
    library.trash_book(b.sha1)

    # the watcher rescans after the moves, and finds the same state
    assert wait_until(lambda: len(rescans) > count)
    time.sleep(DELAY * 3)
    assert present_names(library) == ["Art/a.pdf"]
    assert not b.present
    assert spy.call_count == 0
