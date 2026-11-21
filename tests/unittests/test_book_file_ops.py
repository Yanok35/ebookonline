import json
import os
import shutil
from pathlib import Path

import pytest

import srcs.book
from srcs.book import BookDir
from srcs.book import Transformed
from srcs.transformations import CoverPage, Transformation
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


def test_move_book_does_not_rescan(library, book):
    """ Only the moved book changes: no rescan of the whole directory """
    make_pdf(Path(library.dirpath) / "c.pdf", title="C")
    library.cache.requests.clear()
    library.rename_book(book.sha1, "renamed")
    assert library.find_book_by_filename("c.pdf") is None
    assert library.cache.requests == []
    with open(library.dbfile) as f:
        entry = next(b for b in json.load(f)["booklist"] if b["sha1"] == book.sha1)
    assert entry["filename"] == "Science/renamed.pdf" and entry["mtime"] == book.mtime
    # found by the next scan (the watcher)
    assert library.rescan() is True
    assert library.find_book_by_filename("c.pdf") is not None


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


def test_file_operations_keep_the_modification_time(library, book):
    root = Path(library.dirpath)
    (root / "Art").mkdir()
    mtime = 1_700_000_000.5
    os.utime(root / "Science" / "a.pdf", (mtime, mtime))
    library.rescan()

    def file_mtime(relpath):
        return os.stat(root / relpath).st_mtime

    library.rename_book(book.sha1, "renamed")
    assert file_mtime("Science/renamed.pdf") == mtime
    library.move_book_to_category(book.sha1, "Art")
    assert file_mtime("Art/renamed.pdf") == mtime
    trashed = library.trash_book(book.sha1)
    assert file_mtime(trashed) == mtime
    library.restore_from_trash(trashed)
    assert file_mtime("Art/renamed.pdf") == mtime
    # and the book.db entry
    assert book.mtime == mtime


def cover_image():
    import pymupdf

    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 90), 0)
    pix.set_rect(pix.irect, (200, 60, 60))
    return pix.tobytes("jpeg")


class Recompressed(Transformation):
    """ A transformation keeping everything: the file saved again (new sha1) """

    name = "recompressed"

    def apply(self, src, dst):
        import pymupdf

        with pymupdf.open(src) as doc:
            doc.set_metadata(dict(doc.metadata, producer="recompressed"))
            doc.save(dst, garbage=3, deflate=True)


def test_cover_in_place(library, book):
    import pymupdf

    root = Path(library.dirpath)
    book.title, book.meta_reviewed = "A book", True
    mtime = 1_700_000_000.5
    os.utime(root / "Science" / "a.pdf", (mtime, mtime))
    library.rescan()
    old_sha1 = book.sha1
    original = (root / "Science" / "a.pdf").read_bytes()
    thumbnail = Path(library.cache.get_thumbname(old_sha1))
    thumbnail.write_bytes(b"old thumbnail")
    library.cache.requests.clear()

    result = library.transform(old_sha1, CoverPage(cover_image()))

    assert result == Transformed("Science/a.pdf", old_sha1, book.sha1,
                                 "Trash/Science/a (original).pdf", 1)
    # in place: one more page, the modification time of the original
    path = root / "Science" / "a.pdf"
    assert pymupdf.open(path).page_count == 2
    assert os.stat(path).st_mtime == mtime
    # the original in the trash
    assert (root / "Trash" / "Science" / "a (original).pdf").read_bytes() == original
    # the same book, its user values, its new sha1, saved
    assert library.find_book_by_filename("Science/a.pdf") is book
    assert book.sha1 != old_sha1 and book.sha1 == srcs.book.sha1_file(path)
    assert (book.title, book.meta_reviewed, book.tags, book.bookmarked) == ("A book", True, "algo", True)
    assert book.mtime == mtime and book.filesize == os.stat(path).st_size
    assert db_filenames(library) == {book.sha1: "Science/a.pdf",
                                     library.find_book_by_filename("b.pdf").sha1: "b.pdf"}
    # a new first page: the thumbnail made again
    assert not thumbnail.exists()
    assert library.cache.requests == [(str(path), book.sha1)]
    # no temporary file left; a rescan finds nothing to do
    assert sorted(p.name for p in (root / "Science").iterdir()) == ["a.pdf"]
    assert not library.rescan()
    assert library.original_in_trash(book.sha1) == "Trash/Science/a (original).pdf"

    # again: the latest original
    library.transform(book.sha1, CoverPage(cover_image()))
    assert pymupdf.open(path).page_count == 3
    assert library.original_in_trash(book.sha1) == "Trash/Science/a (original) (2).pdf"


def test_restore_original(library, book):
    import pymupdf

    root = Path(library.dirpath)
    path = root / "Science" / "a.pdf"
    sha1s = [book.sha1]
    for _ in range(2):
        sha1s.append(library.transform(book.sha1, CoverPage(cover_image())).new_sha1)

    result = library.restore_original(book.sha1)
    assert result == Transformed("Science/a.pdf", sha1s[2], sha1s[1],
                                 "Trash/Science/a (transformed).pdf", -1)
    assert book.sha1 == sha1s[1] and pymupdf.open(path).page_count == 2
    assert library.original_in_trash(book.sha1) == "Trash/Science/a (original).pdf"
    # and again: the first file
    library.restore_original(book.sha1)
    assert book.sha1 == sha1s[0] and pymupdf.open(path).page_count == 1
    assert library.original_in_trash(book.sha1) is None
    assert sorted(p.name for p in (root / "Trash" / "Science").iterdir()) == \
        ["a (transformed) (2).pdf", "a (transformed).pdf"]
    with pytest.raises(BookFileError, match="no original in the trash"):
        library.restore_original(book.sha1)
    assert not library.rescan()


def test_transform_keeping_first_page_and_text(library, book):
    """ the thumbnail and the metadata analysis follow the book """
    from srcs import pdfstats
    from srcs.metadata import store

    cache_dir = library.cache.cachedir
    old_sha1 = book.sha1
    Path(library.cache.get_thumbname(old_sha1)).write_bytes(b"thumbnail")
    store.write(cache_dir, {"sha1": old_sha1, "raw": {}, "candidates": {}})
    Path(pdfstats.path(cache_dir, old_sha1)).write_text("{}")
    library.cache.requests.clear()

    result = library.transform(old_sha1, Recompressed())
    assert result.page_offset == 0
    assert Path(library.cache.get_thumbname(book.sha1)).read_bytes() == b"thumbnail"
    assert not Path(library.cache.get_thumbname(old_sha1)).exists()
    assert store.read(cache_dir, book.sha1)["sha1"] == book.sha1
    assert store.read(cache_dir, old_sha1) is None
    # the indicators: of the new file, measured when asked
    assert not Path(pdfstats.path(cache_dir, old_sha1)).exists()
    assert library.cache.requests == []


def test_transform_refused(library, book, tmp_bookdir):
    root = Path(library.dirpath)
    with pytest.raises(BookFileError, match="not a JPEG or PNG image"):
        library.transform(book.sha1, CoverPage(b"not an image"))
    with pytest.raises(BookFileError, match="unknown book"):
        library.transform("0" * 40, CoverPage(cover_image()))
    (root / "bad.pdf").write_bytes(b"not a PDF file")
    library.rescan()
    with pytest.raises(BookFileError, match="can not read the PDF file"):
        library.transform(library.find_book_by_filename("bad.pdf").sha1, CoverPage(cover_image()))
    # a copy of the book in the library
    shutil.copy(root / "b.pdf", root / "copy of b.pdf")
    library.rescan()
    with pytest.raises(BookFileError, match="has copies in the library"):
        library.transform(library.find_book_by_filename("b.pdf").sha1, CoverPage(cover_image()))
    # nothing written
    assert sorted(p.name for p in root.rglob("*")) == \
        ["Science", "a.pdf", "b.pdf", "bad.pdf", "copy of b.pdf"]

    reopened = BookDir(library.dbfile, FakeCache(tmp_bookdir[2]), read_only=True)
    reopened.open(library.dirpath)
    with pytest.raises(BookFileError, match="read-only"):
        reopened.transform(book.sha1, CoverPage(cover_image()))


def test_transform_check_failed(library, book):
    class Broken(Transformation):
        name = "broken"

        def apply(self, src, dst):
            import pymupdf

            doc = pymupdf.open()
            page = doc.new_page(width=210, height=297)
            page.insert_text((20, 40), "Another text")
            doc.save(dst)

    root = Path(library.dirpath)
    original = (root / "Science" / "a.pdf").read_bytes()
    with pytest.raises(BookFileError, match="broken: the text of page 1 changed"):
        library.transform(book.sha1, Broken())
    assert (root / "Science" / "a.pdf").read_bytes() == original
    assert not (root / "Trash").exists()
    assert sorted(p.name for p in (root / "Science").iterdir()) == ["a.pdf"]


def test_scan_compares_the_size(library, book, mocker):
    """ a file changed with the same modification time, another size: hashed again """
    root = Path(library.dirpath)
    path = root / "Science" / "a.pdf"
    mtime = os.path.getmtime(path)
    make_pdf(path, title="A longer title, another content")
    os.utime(path, (mtime, mtime))
    library.rescan()
    assert book.sha1 == srcs.book.sha1_file(path)
