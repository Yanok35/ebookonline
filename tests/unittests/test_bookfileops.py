import os

import pytest

from srcs.bookfileops import (
    BookFileError,
    category_of,
    check_inside,
    check_relpath,
    ensure_trash,
    is_ignored,
    list_categories,
    list_trash,
    move_no_replace,
    move_to_free_name,
)


def test_category_of():
    assert category_of("a.pdf") == "Generals"
    assert category_of("Science/a.pdf") == "Science"
    assert category_of("Science/sub/a.pdf") == "Science"


def test_check_relpath():
    assert check_relpath("Science/a b.pdf") == "Science/a b.pdf"
    assert check_relpath("a.PDF") == "a.PDF"


@pytest.mark.parametrize("relpath", [
    "", "  ", "/etc/a.pdf", "../a.pdf", "Science/../../a.pdf", "./a.pdf",
    "Science//a.pdf", "Science/", ".hidden.pdf", ".private/a.pdf",
    "a.txt", "a", ".pdf", "a.pdf\0", "a\\b.pdf", " a.pdf", "Science /a.pdf",
])
def test_check_relpath_refused(relpath):
    with pytest.raises(BookFileError):
        check_relpath(relpath)


def test_check_inside(tmp_path):
    book_dir = tmp_path / "books"
    (book_dir / "Science").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, book_dir / "link")

    assert check_inside(str(book_dir), "Science/a.pdf") == str(book_dir / "Science/a.pdf")
    # a missing directory is checked from its nearest existing parent
    check_inside(str(book_dir), "New/sub/a.pdf")
    with pytest.raises(BookFileError):
        check_inside(str(book_dir), "link/a.pdf")
    with pytest.raises(BookFileError):
        check_inside(str(book_dir), "link/new/a.pdf")


def test_check_inside_symlinked_book_dir(tmp_path):
    real = tmp_path / "real"
    (real / "Science").mkdir(parents=True)
    os.symlink(real, tmp_path / "books")
    check_inside(str(tmp_path / "books"), "Science/a.pdf")


def test_is_ignored(tmp_path):
    (tmp_path / "private" / "sub").mkdir(parents=True)
    (tmp_path / "private" / ".ebook-ignore-dir").touch()
    assert not is_ignored(str(tmp_path), "a.pdf")
    assert not is_ignored(str(tmp_path), "Science/a.pdf")
    assert is_ignored(str(tmp_path), "private/a.pdf")
    assert is_ignored(str(tmp_path), "private/sub/a.pdf")
    # the trash, even before it is created
    assert is_ignored(str(tmp_path), "Trash/a.pdf")


def test_move_no_replace(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_text("A")
    move_no_replace(str(src), str(tmp_path / "new" / "dir" / "b.pdf"))
    assert not src.exists()
    assert (tmp_path / "new" / "dir" / "b.pdf").read_text() == "A"


def test_move_no_replace_never_overwrites(tmp_path):
    (tmp_path / "a.pdf").write_text("A")
    (tmp_path / "b.pdf").write_text("B")
    with pytest.raises(BookFileError):
        move_no_replace(str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf"))
    assert (tmp_path / "a.pdf").read_text() == "A"
    assert (tmp_path / "b.pdf").read_text() == "B"


def test_move_no_replace_missing_source(tmp_path):
    with pytest.raises(BookFileError):
        move_no_replace(str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf"))
    assert not (tmp_path / "b.pdf").exists()


def test_move_no_replace_failure_removes_the_reserved_name(tmp_path, mocker):
    (tmp_path / "a.pdf").write_text("A")
    mocker.patch("os.replace", side_effect=PermissionError(13, "Permission denied"))
    with pytest.raises(BookFileError):
        move_no_replace(str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf"))
    assert (tmp_path / "a.pdf").read_text() == "A"
    assert not (tmp_path / "b.pdf").exists()


def test_move_to_free_name(tmp_path):
    for name in ["a.pdf", "Trash/a.pdf", "Trash/a (2).pdf"]:
        (tmp_path / name).parent.mkdir(exist_ok=True)
        (tmp_path / name).write_text(name)
    dst = move_to_free_name(str(tmp_path / "a.pdf"), str(tmp_path / "Trash/a.pdf"))
    assert dst == str(tmp_path / "Trash/a (3).pdf")
    assert (tmp_path / "Trash/a (3).pdf").read_text() == "a.pdf"
    assert (tmp_path / "Trash/a.pdf").read_text() == "Trash/a.pdf"


def test_ensure_trash(tmp_path):
    trash = ensure_trash(str(tmp_path))
    assert trash == str(tmp_path / "Trash")
    assert (tmp_path / "Trash" / ".ebook-ignore-dir").exists()
    # again: nothing changes
    ensure_trash(str(tmp_path))


def test_list_categories(tmp_path):
    for name in ["Science", "art", "Trash", ".hidden", "private", "Zoo"]:
        (tmp_path / name).mkdir()
    (tmp_path / "private" / ".ebook-ignore-dir").touch()
    (tmp_path / "a.pdf").touch()
    os.symlink(tmp_path / "Science", tmp_path / "link")
    assert list_categories(str(tmp_path)) == ["art", "Science", "Zoo"]


def test_list_trash(tmp_path):
    assert list_trash(str(tmp_path)) == []
    ensure_trash(str(tmp_path))
    for name in ["Trash/b.pdf", "Trash/Science/a.pdf", "Trash/notes.txt", "Trash/.hidden/c.pdf"]:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x" * 10)
    files = list_trash(str(tmp_path))
    assert [(f.filename, f.original) for f in files] == \
        [("Trash/b.pdf", "b.pdf"), ("Trash/Science/a.pdf", "Science/a.pdf")]
    assert files[0].filesize == 10
