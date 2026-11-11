import json
from pathlib import Path

import srcs.book

from tests.conftest import make_pdf


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
