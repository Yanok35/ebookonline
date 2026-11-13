import json
import os
import shutil
from pathlib import Path

import srcs.book
from srcs.book import BookDir

from tests.conftest import FakeCache, make_pdf


def names(books):
    return sorted(b.filename for b in books)


def db_entries(library):
    with open(library.dbfile) as f:
        return {b["filename"]: b for b in json.load(f)["booklist"]}


def test_initial_scan(library):
    root = Path(library.dirpath)
    make_pdf(root / "a.pdf")
    make_pdf(root / "Science" / "b.pdf")
    make_pdf(root / "Science" / "sub" / "c.PDF")
    (root / "notes.txt").write_text("not a book")

    assert library.rescan() is True

    assert names(library.get_booklist()) == ["Science/b.pdf", "Science/sub/c.PDF", "a.pdf"]
    categories = {b.filename: b.category for b in library.get_booklist()}
    assert categories == {"a.pdf": "Generals", "Science/b.pdf": "Science",
                          "Science/sub/c.PDF": "Science"}
    # one thumbnail request per book, saved database
    assert len(library.cache.requests) == 3
    assert set(db_entries(library)) == {"a.pdf", "Science/b.pdf", "Science/sub/c.PDF"}


def test_rescan_only_hashes_new_files(library, mocker):
    root = Path(library.dirpath)
    make_pdf(root / "a.pdf")
    library.rescan()

    spy = mocker.spy(srcs.book, "sha1_file")
    assert library.rescan() is False
    assert spy.call_count == 0

    make_pdf(root / "b.pdf")
    assert library.rescan() is True
    assert spy.call_count == 1
    assert names(library.get_booklist()) == ["a.pdf", "b.pdf"]


def test_move_keeps_user_settings(library):
    root = Path(library.dirpath)
    make_pdf(root / "a.pdf")
    library.rescan()
    book = library.get_booklist()[0]
    book.bookmarked = True
    book.tags = "python"

    (root / "Art").mkdir()
    shutil.move(root / "a.pdf", root / "Art" / "renamed.pdf")
    library.rescan()

    assert library.get_booklist() == [book]
    assert book.filename == "Art/renamed.pdf"
    assert book.category == "Art"
    assert book.bookmarked and book.tags == "python"
    assert len(library.booklist) == 1


def test_deleted_book_is_hidden_kept_and_restored(library):
    root = Path(library.dirpath)
    make_pdf(root / "a.pdf", title="A")
    make_pdf(root / "b.pdf")
    library.rescan()
    book = library.find_book_by_filename("a.pdf")
    book.bookmarked = True
    sha1 = book.sha1

    os.remove(root / "a.pdf")
    assert library.rescan() is True

    # hidden from every view...
    assert names(library.get_booklist()) == ["b.pdf"]
    assert library.get_subset_if_bookmarked() == []
    assert library.get_subset_by_regexp("a") == []
    assert names(library.sort_by_date()) == ["b.pdf"]
    # ... but kept, in memory and in book.db
    assert library.find_book_by_sha1(sha1) is book
    assert not book.present
    assert db_entries(library)["a.pdf"]["mtime"] == -1

    # same content comes back, elsewhere: settings are restored
    make_pdf(root / "Back" / "a-again.pdf", title="A")
    library.rescan()
    assert book.present
    assert book.filename == "Back/a-again.pdf"
    assert book.bookmarked
    assert len(library.booklist) == 2


def test_load_db_keeps_missing_books(library, tmp_bookdir):
    root = Path(library.dirpath)
    make_pdf(root / "a.pdf")
    make_pdf(root / "b.pdf")
    library.rescan()
    library.find_book_by_filename("a.pdf").bookmarked = True
    library.save_db()

    # file removed while the server is stopped
    os.remove(root / "a.pdf")
    reopened = BookDir(library.dbfile, FakeCache(tmp_bookdir[2]))
    reopened.open(library.dirpath)

    missing = reopened.find_book_by_filename("a.pdf")
    assert missing is not None and not missing.present and missing.bookmarked
    assert names(reopened.get_booklist()) == ["b.pdf"]


def test_file_replaced_in_place(library):
    root = Path(library.dirpath)
    make_pdf(root / "a.pdf", title="v1")
    library.rescan()
    book = library.get_booklist()[0]
    book.bookmarked = True
    old_sha1 = book.sha1

    make_pdf(root / "a.pdf", title="v2")
    st = os.stat(root / "a.pdf")
    os.utime(root / "a.pdf", ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    library.cache.requests.clear()
    library.rescan()

    assert library.booklist == [book]
    assert book.sha1 != old_sha1 and book.bookmarked
    assert library.cache.requests == [(str(root / "a.pdf"), book.sha1)]


def test_duplicate_is_not_added(library):
    root = Path(library.dirpath)
    make_pdf(root / "a.pdf", title="same")
    make_pdf(root / "copy" / "a.pdf", title="same")
    library.rescan()

    assert len(library.booklist) == 1


def test_ignore_dir_marker(library):
    root = Path(library.dirpath)
    make_pdf(root / "a.pdf")
    make_pdf(root / "private" / "b.pdf")
    (root / "private" / ".ebook-ignore-dir").touch()
    library.rescan()

    assert names(library.get_booklist()) == ["a.pdf"]


def test_save_db_is_atomic(library):
    root = Path(library.dirpath)
    make_pdf(root / "a.pdf")
    library.rescan()

    # no temporary file left behind
    leftovers = [p for p in Path(library.dbfile).parent.iterdir()
                 if p.name.startswith(".book_db_")]
    assert leftovers == []
    assert set(db_entries(library)) == {"a.pdf"}


def test_get_all_books_includes_missing(library):
    root = Path(library.dirpath)
    make_pdf(root / "a.pdf")
    make_pdf(root / "b.pdf")
    library.rescan()
    os.remove(root / "a.pdf")
    library.rescan()

    assert names(library.get_all_books()) == ["a.pdf", "b.pdf"]
    assert names(library.get_booklist()) == ["b.pdf"]
