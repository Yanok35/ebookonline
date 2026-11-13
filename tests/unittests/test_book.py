import json
import os
import shutil
from pathlib import Path

import pytest

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


def test_book_metadata_is_saved(library, tmp_bookdir):
    root = Path(library.dirpath)
    make_pdf(root / "a.pdf")
    library.rescan()
    book = library.find_book_by_filename("a.pdf")
    book.tags, book.editor, book.year, book.isbn = "algo", "O'Reilly", 2022, "9781098113162"
    library.save_db()

    reopened = BookDir(library.dbfile, FakeCache(tmp_bookdir[2]))
    reopened.open(library.dirpath)
    book = reopened.find_book_by_filename("a.pdf")
    assert (book.tags, book.editor, book.year, book.isbn) == ("algo", "O'Reilly", 2022, "9781098113162")


def test_book_metadata_defaults_with_an_old_db(library, tmp_bookdir):
    root = Path(library.dirpath)
    make_pdf(root / "a.pdf")
    library.rescan()
    # book.db written before editor, year and isbn were saved
    with open(library.dbfile) as f:
        db = json.load(f)
    for b in db["booklist"]:
        del b["editor"], b["year"], b["isbn"]
    with open(library.dbfile, "w") as f:
        json.dump(db, f)

    reopened = BookDir(library.dbfile, FakeCache(tmp_bookdir[2]))
    reopened.open(library.dirpath)
    book = reopened.find_book_by_filename("a.pdf")
    assert (book.editor, book.year, book.isbn) == ("", 0, "")


def test_db_has_a_schema_version(library):
    make_pdf(Path(library.dirpath) / "a.pdf")
    library.rescan()
    with open(library.dbfile) as f:
        assert json.load(f)["version"] == srcs.book.DB_VERSION


def test_db_without_version_is_migrated(library, tmp_bookdir):
    root = Path(library.dirpath)
    make_pdf(root / "a.pdf")
    library.rescan()
    library.find_book_by_filename("a.pdf").tags = "algo"
    library.save_db()
    # book.db written before the schema version was added
    with open(library.dbfile) as f:
        db = json.load(f)
    del db["version"]
    with open(library.dbfile, "w") as f:
        json.dump(db, f)
    old_content = Path(library.dbfile).read_text()

    reopened = BookDir(library.dbfile, FakeCache(tmp_bookdir[2]))
    reopened.open(library.dirpath)

    assert reopened.find_book_by_filename("a.pdf").tags == "algo"
    # the previous file is kept, the database is saved in the current version
    assert Path(library.dbfile + ".v0.bak").read_text() == old_content
    with open(library.dbfile) as f:
        assert json.load(f)["version"] == srcs.book.DB_VERSION


def test_db_backup_is_not_overwritten(library, tmp_bookdir):
    make_pdf(Path(library.dirpath) / "a.pdf")
    library.rescan()
    backup = Path(library.dbfile + ".v0.bak")
    backup.write_text("first backup")
    with open(library.dbfile) as f:
        db = json.load(f)
    del db["version"]
    with open(library.dbfile, "w") as f:
        json.dump(db, f)

    BookDir(library.dbfile, FakeCache(tmp_bookdir[2])).open(library.dirpath)
    assert backup.read_text() == "first backup"


def test_current_db_is_not_rewritten(library, tmp_bookdir):
    make_pdf(Path(library.dirpath) / "a.pdf")
    library.rescan()
    mtime = os.stat(library.dbfile).st_mtime_ns

    BookDir(library.dbfile, FakeCache(tmp_bookdir[2])).open(library.dirpath)
    assert os.stat(library.dbfile).st_mtime_ns == mtime
    assert not list(Path(library.dbfile).parent.glob("*.bak"))


def test_newer_db_is_refused(library, tmp_bookdir):
    make_pdf(Path(library.dirpath) / "a.pdf")
    library.rescan()
    with open(library.dbfile) as f:
        db = json.load(f)
    # an incompatible change: this version can not read it
    db["version"] = db["min_reader_version"] = srcs.book.DB_VERSION + 1
    with open(library.dbfile, "w") as f:
        json.dump(db, f)
    content = Path(library.dbfile).read_text()

    with pytest.raises(srcs.book.BookDbVersionError):
        BookDir(library.dbfile, FakeCache(tmp_bookdir[2])).open(library.dirpath)
    # left untouched
    assert Path(library.dbfile).read_text() == content


def test_migrations_are_applied_in_order(library, tmp_bookdir, monkeypatch):
    make_pdf(Path(library.dirpath) / "a.pdf")
    library.rescan()
    with open(library.dbfile) as f:
        db = json.load(f)
    del db["version"]
    db["booklist"][0]["tags"] = "a"
    with open(library.dbfile, "w") as f:
        json.dump(db, f)

    # a fake version 2, whose migration depends on the one to version 1
    def migrate_v0(db):
        for b in db["booklist"]:
            b["tags"] += " v1"
        return db

    def migrate_v1(db):
        for b in db["booklist"]:
            b["tags"] += " v2"
        return db

    monkeypatch.setattr(srcs.book, "DB_VERSION", 2)
    monkeypatch.setattr(srcs.book, "_MIGRATIONS", [migrate_v0, migrate_v1])

    reopened = BookDir(library.dbfile, FakeCache(tmp_bookdir[2]))
    reopened.open(library.dirpath)
    assert reopened.find_book_by_filename("a.pdf").tags == "a v1 v2"
    with open(library.dbfile) as f:
        assert json.load(f)["version"] == 2


def test_duplicate_does_not_replace_known_book(library):
    root = Path(library.dirpath)
    make_pdf(root / "Science" / "book.pdf", title="same")
    library.rescan()
    book = library.get_booklist()[0]
    book.tags = "python"

    # copies, before and after the book in any walk order
    for path in ["a.pdf", "Art/book.pdf", "Zoo/book.pdf", "Science/zz.pdf"]:
        make_pdf(root / path, title="same")
    for _ in range(2):
        library.rescan()
        assert library.booklist == [book]
        assert book.filename == "Science/book.pdf" and book.tags == "python"


def test_duplicates_of_a_new_book(library):
    root = Path(library.dirpath)
    for path in ["b.pdf", "Art/a.pdf", "a.pdf"]:
        make_pdf(root / path, title="same")
    library.rescan()

    # the first file, sorted by path
    assert names(library.booklist) == ["Art/a.pdf"]


def test_duplicate_replaces_a_removed_book(library):
    root = Path(library.dirpath)
    make_pdf(root / "a.pdf", title="same")
    library.rescan()
    book = library.get_booklist()[0]
    book.bookmarked = True
    make_pdf(root / "copy" / "a.pdf", title="same")
    library.rescan()

    os.remove(root / "a.pdf")
    library.rescan()
    assert library.booklist == [book]
    assert book.filename == "copy/a.pdf" and book.present and book.bookmarked


def test_duplicates_are_kept_and_not_hashed_again(library, mocker):
    root = Path(library.dirpath)
    make_pdf(root / "a.pdf", title="same")
    make_pdf(root / "copy" / "a.pdf", title="same")
    make_pdf(root / "b.pdf")
    library.rescan()
    assert [(d.filename, d.sha1) for d in library.duplicates] == \
        [("copy/a.pdf", library.find_book_by_filename("a.pdf").sha1)]

    spy = mocker.spy(srcs.book, "sha1_file")
    assert library.rescan() is False
    assert spy.call_count == 0

    # a removed copy is no longer a duplicate
    os.remove(root / "copy" / "a.pdf")
    assert library.rescan() is True
    assert library.duplicates == []


def test_duplicates_are_saved(library, tmp_bookdir, mocker):
    root = Path(library.dirpath)
    make_pdf(root / "a.pdf", title="same")
    make_pdf(root / "copy" / "a.pdf", title="same")
    library.rescan()

    reopened = BookDir(library.dbfile, FakeCache(tmp_bookdir[2]))
    reopened.open(library.dirpath)
    assert reopened.duplicates == library.duplicates

    spy = mocker.spy(srcs.book, "sha1_file")
    assert reopened.rescan() is False
    assert spy.call_count == 0


def test_db_version_1_is_migrated(library, tmp_bookdir):
    make_pdf(Path(library.dirpath) / "a.pdf")
    library.rescan()
    with open(library.dbfile) as f:
        db = json.load(f)
    db["version"] = 1
    del db["duplicates"]
    with open(library.dbfile, "w") as f:
        json.dump(db, f)

    reopened = BookDir(library.dbfile, FakeCache(tmp_bookdir[2]))
    reopened.open(library.dirpath)
    assert reopened.duplicates == []
    with open(library.dbfile) as f:
        db = json.load(f)
    assert db["version"] == 2 and db["duplicates"] == []
    assert Path(library.dbfile + ".v1.bak").exists()


def test_get_duplicates(library):
    root = Path(library.dirpath)
    for path in ["a.pdf", "z/a.pdf", "copy/a.pdf"]:
        make_pdf(root / path, title="A")
    make_pdf(root / "b.pdf", title="B")
    make_pdf(root / "c.pdf", title="C")
    make_pdf(root / "copy/c.pdf", title="C")
    library.rescan()

    duplicates = library.get_duplicates()
    a = library.find_book_by_filename("a.pdf")
    c = library.find_book_by_filename("c.pdf")
    assert {sha1: [d.filename for d in files] for sha1, files in duplicates.items()} == \
        {a.sha1: ["copy/a.pdf", "z/a.pdf"], c.sha1: ["copy/c.pdf"]}
