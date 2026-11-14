import json
import os
from pathlib import Path

import pytest

import srcs.book
from srcs.book import BookDir
from srcs.bookfileops import BookFileError

from tests.conftest import FakeCache, make_pdf


@pytest.fixture
def book(library):
    """ Science/a.pdf, with user settings """
    make_pdf(Path(library.dirpath) / "Science" / "a.pdf", title="A")
    make_pdf(Path(library.dirpath) / "b.pdf", title="B")
    library.rescan()
    book = library.find_book_by_filename("Science/a.pdf")
    book.tags, book.bookmarked = "algo", True
    return book


def db_filenames(library):
    with open(library.dbfile) as f:
        return {b["sha1"]: b["filename"] for b in json.load(f)["booklist"]}


def test_move_book(library, book, mocker):
    root = Path(library.dirpath)
    mtime = os.path.getmtime(root / "Science" / "a.pdf")
    spy = mocker.spy(srcs.book, "sha1_file")

    assert library.move_book(book.sha1, "Art/new/a-renamed.pdf") == "Art/new/a-renamed.pdf"

    assert not (root / "Science" / "a.pdf").exists()
    assert os.path.getmtime(root / "Art" / "new" / "a-renamed.pdf") == mtime
    # same book, user settings kept, saved at once, nothing hashed again
    assert library.find_book_by_filename("Art/new/a-renamed.pdf") is book
    assert book.category == "Art" and book.tags == "algo" and book.bookmarked
    assert db_filenames(library)[book.sha1] == "Art/new/a-renamed.pdf"
    assert spy.call_count == 0
    assert library.rescan() is False


def test_move_book_to_the_root(library, book):
    library.move_book(book.sha1, "a.pdf")
    assert book.filename == "a.pdf" and book.category == "Generals"


def test_rename_book(library, book):
    assert library.rename_book(book.sha1, "A new name") == "Science/A new name.pdf"
    assert (Path(library.dirpath) / "Science" / "A new name.pdf").exists()
    assert book.filename == "Science/A new name.pdf" and book.category == "Science"
    assert library.rename_book(book.sha1, "again.PDF") == "Science/again.PDF"


@pytest.mark.parametrize("name", ["", "sub/a.pdf", "../a.pdf", ".hidden.pdf", " a.pdf"])
def test_rename_book_refused(library, book, name):
    with pytest.raises(BookFileError):
        library.rename_book(book.sha1, name)
    assert (Path(library.dirpath) / "Science" / "a.pdf").exists()
    assert book.filename == "Science/a.pdf"


@pytest.mark.parametrize("relpath", [
    "b.pdf",                    # existing file
    "../outside.pdf",           # outside of the book directory
    "/tmp/a.pdf",
    "Trash/a.pdf",              # the trash
    "private/a.pdf",            # an ignored directory
    "Science/a.txt",            # not a PDF
])
def test_move_book_refused(library, book, relpath):
    root = Path(library.dirpath)
    (root / "private").mkdir()
    (root / "private" / ".ebook-ignore-dir").touch()
    with pytest.raises(BookFileError):
        library.move_book(book.sha1, relpath)
    assert (root / "Science" / "a.pdf").exists() and (root / "b.pdf").exists()
    assert book.filename == "Science/a.pdf"
    assert not (root.parent / "outside.pdf").exists()


def test_move_book_through_a_symlink_outside(library, book, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, Path(library.dirpath) / "link")
    with pytest.raises(BookFileError):
        library.move_book(book.sha1, "link/a.pdf")
    assert list(outside.iterdir()) == []


def test_move_unknown_or_missing_book(library, book):
    with pytest.raises(BookFileError):
        library.move_book("0" * 40, "c.pdf")
    os.remove(Path(library.dirpath) / "Science" / "a.pdf")
    library.rescan()
    with pytest.raises(BookFileError):
        library.move_book(book.sha1, "c.pdf")
    with pytest.raises(BookFileError):
        library.trash_book(book.sha1)


def test_move_book_to_its_own_path(library, book):
    assert library.move_book(book.sha1, "Science/a.pdf") == "Science/a.pdf"
    assert (Path(library.dirpath) / "Science" / "a.pdf").exists()


def test_trash_book(library, book, tmp_bookdir):
    root = Path(library.dirpath)
    assert library.trash_book(book.sha1) == "Trash/Science/a.pdf"

    assert (root / "Trash" / "Science" / "a.pdf").exists()
    assert (root / "Trash" / ".ebook-ignore-dir").exists()
    # kept, missing, with its settings, also in book.db
    assert not book.present and book.tags == "algo" and book.bookmarked
    assert [b.filename for b in library.get_booklist()] == ["b.pdf"]
    reopened = BookDir(library.dbfile, FakeCache(tmp_bookdir[2]))
    reopened.open(library.dirpath)
    assert not reopened.find_book_by_sha1(book.sha1).present
    # still out of the library after a rescan
    library.rescan()
    assert not book.present

    # back from the trash: the book is found again, with its settings
    os.rename(root / "Trash" / "Science" / "a.pdf", root / "a.pdf")
    library.rescan()
    assert book.present and book.filename == "a.pdf" and book.bookmarked


def test_trash_book_with_a_duplicate(library, book):
    root = Path(library.dirpath)
    make_pdf(root / "copy" / "a.pdf", title="A")
    library.rescan()
    assert [d.filename for d in library.duplicates] == ["copy/a.pdf"]

    library.trash_book(book.sha1)
    # the duplicate replaces the book, with its settings
    assert book.present and book.filename == "copy/a.pdf" and book.bookmarked
    assert library.duplicates == []


def test_trash_name_collision(library, book):
    root = Path(library.dirpath)
    make_pdf(root / "Trash" / "Science" / "a.pdf", title="older")
    assert library.trash_book(book.sha1) == "Trash/Science/a (2).pdf"
    assert (root / "Trash" / "Science" / "a.pdf").exists()


def test_trash_duplicate(library, book):
    root = Path(library.dirpath)
    make_pdf(root / "copy" / "a.pdf", title="A")
    make_pdf(root / "z.pdf", title="A")
    library.rescan()

    assert library.trash_duplicate("copy/a.pdf") == "Trash/copy/a.pdf"
    assert (root / "Trash" / "copy" / "a.pdf").exists()
    assert [d.filename for d in library.duplicates] == ["z.pdf"]
    # the book is unchanged
    assert book.present and book.filename == "Science/a.pdf"


@pytest.mark.parametrize("relpath", ["Science/a.pdf", "b.pdf", "missing.pdf", "../x.pdf"])
def test_trash_duplicate_refused(library, book, relpath):
    # books are not duplicates
    with pytest.raises(BookFileError):
        library.trash_duplicate(relpath)
    assert book.present


def test_file_operations_in_read_only_mode(library, book, tmp_bookdir):
    with open(library.dbfile) as f:
        db = json.load(f)
    db["version"] = srcs.book.DB_VERSION + 1
    with open(library.dbfile, "w") as f:
        json.dump(db, f)
    content = Path(library.dbfile).read_text()
    reopened = BookDir(library.dbfile, FakeCache(tmp_bookdir[2]))
    reopened.open(library.dirpath)
    assert reopened.read_only

    # nothing is written: neither the files, nor book.db
    root = Path(library.dirpath)
    (root / "Trash").mkdir()
    make_pdf(root / "Trash" / "c.pdf", title="C")
    make_pdf(root / "copy" / "a.pdf", title="A")
    reopened.rescan()
    bookfiles = sorted(root.rglob("*"))
    for operation in [lambda: reopened.rename_book(book.sha1, "renamed"),
                      lambda: reopened.move_book(book.sha1, "a.pdf"),
                      lambda: reopened.move_book_to_category(book.sha1, ""),
                      lambda: reopened.trash_book(book.sha1),
                      lambda: reopened.trash_duplicate("copy/a.pdf"),
                      lambda: reopened.restore_from_trash("Trash/c.pdf")]:
        with pytest.raises(BookFileError, match="read-only"):
            operation()
    assert reopened.find_book_by_sha1(book.sha1).filename == "Science/a.pdf"
    assert sorted(root.rglob("*")) == bookfiles
    assert Path(library.dbfile).read_text() == content


def test_file_operations_when_opened_read_only(library, book, tmp_bookdir):
    reopened = BookDir(library.dbfile, FakeCache(tmp_bookdir[2]), read_only=True)
    reopened.open(library.dirpath)
    with pytest.raises(BookFileError, match="read-only"):
        reopened.rename_book(book.sha1, "renamed")
    assert (Path(library.dirpath) / "Science" / "a.pdf").exists()


def test_move_book_to_category(library, book):
    root = Path(library.dirpath)
    (root / "Art").mkdir()
    make_pdf(root / "Science" / "sub" / "c.pdf", title="C")
    library.rescan()
    c = library.find_book_by_filename("Science/sub/c.pdf")

    assert library.move_book_to_category(book.sha1, "Art") == "Art/a.pdf"
    assert book.category == "Art" and book.tags == "algo"
    # the file goes to the category directory itself
    assert library.move_book_to_category(c.sha1, "Art") == "Art/c.pdf"
    # '': the root of the book directory
    assert library.move_book_to_category(book.sha1, "") == "a.pdf"
    assert book.category == "Generals"


@pytest.mark.parametrize("category", ["New", "Trash", "private", "Science/sub", "..", "link"])
def test_move_book_to_category_refused(library, book, category, tmp_path):
    root = Path(library.dirpath)
    (root / "private").mkdir()
    (root / "private" / ".ebook-ignore-dir").touch()
    (root / "Science" / "sub").mkdir()
    (root / "Trash").mkdir()
    os.symlink(tmp_path, root / "link")
    with pytest.raises(BookFileError):
        library.move_book_to_category(book.sha1, category)
    assert book.filename == "Science/a.pdf"
    assert not (root / "New").exists()


def test_restore_from_trash(library, book):
    root = Path(library.dirpath)
    trashed = library.trash_book(book.sha1)
    os.rmdir(root / "Science")  # the category was removed in the meantime

    assert library.restore_from_trash(trashed) == "Science/a.pdf"
    assert (root / "Science" / "a.pdf").exists()
    assert not (root / "Trash" / "Science" / "a.pdf").exists()
    # the book is back, with its settings
    assert book.present and book.filename == "Science/a.pdf"
    assert book.tags == "algo" and book.bookmarked


def test_restore_a_duplicate_from_trash(library, book):
    make_pdf(Path(library.dirpath) / "copy" / "a.pdf", title="A")
    library.rescan()
    trashed = library.trash_duplicate("copy/a.pdf")
    assert library.duplicates == []
    library.restore_from_trash(trashed)
    assert [d.filename for d in library.duplicates] == ["copy/a.pdf"]
    assert book.filename == "Science/a.pdf"


def test_restore_from_trash_never_overwrites(library, book):
    root = Path(library.dirpath)
    trashed = library.trash_book(book.sha1)
    make_pdf(root / "Science" / "a.pdf", title="another one")
    with pytest.raises(BookFileError, match="already exists"):
        library.restore_from_trash(trashed)
    assert (root / trashed).exists()


@pytest.mark.parametrize("relpath", [
    "Science/a.pdf",            # not in the trash
    "Trash/missing.pdf",
    "Trash/../b.pdf",
    "Trash",
])
def test_restore_from_trash_refused(library, book, relpath):
    library.trash_book(book.sha1)
    with pytest.raises(BookFileError):
        library.restore_from_trash(relpath)
    assert (Path(library.dirpath) / "Trash" / "Science" / "a.pdf").exists()
