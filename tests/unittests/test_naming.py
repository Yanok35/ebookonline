""" Names of the PDF files after a pattern (srcs/naming.py) """

import pytest

from srcs.naming import (
    MAX_NAME_BYTES,
    NamingError,
    author_sort,
    check_pattern,
    clean,
    file_name,
    free_name,
)

PATTERN = "{author_sort} - {title} ({year})"


class Book:
    def __init__(self, title="", authors=(), editor="", year=0, isbn=""):
        self.title, self.authors, self.editor = title, list(authors), editor
        self.year, self.isbn = year, isbn


@pytest.mark.parametrize("book, expected", [
    (Book("Les Misérables", ["Victor Hugo"], year=2012), "Hugo, Victor - Les Misérables (2012).pdf"),
    # missing values: left out with their parentheses, separator
    (Book("Les Misérables", ["Victor Hugo"]), "Hugo, Victor - Les Misérables.pdf"),
    (Book("Les Misérables", year=2012), "Les Misérables (2012).pdf"),
    (Book("Les Misérables"), "Les Misérables.pdf"),
    # characters which are not allowed in a file name (or on Windows)
    (Book("Python Algorithms: Mastering / Basics?", ["Magnus Lie Hetland"], year=2010),
     "Hetland, Magnus Lie - Python Algorithms - Mastering - Basics (2010).pdf"),
])
def test_file_name(book, expected):
    assert file_name(PATTERN, book) == expected


@pytest.mark.parametrize("book, expected", [
    (Book("Les Misérables", ["Victor Hugo"], year=2012), "Les Misérables - Hugo, Victor, 2012.pdf"),
    (Book("Les Misérables", ["Victor Hugo"]), "Les Misérables - Hugo, Victor.pdf"),
    # the comma is kept with the year, not the separator
    (Book("Les Misérables", year=2012), "Les Misérables, 2012.pdf"),
    (Book("Les Misérables"), "Les Misérables.pdf"),
])
def test_file_name_default_pattern(book, expected):
    from config import Config
    assert Config.FILENAME_PATTERN == "{title} - {author_sort}, {year}"
    assert file_name(Config.FILENAME_PATTERN, book) == expected


def test_file_name_variables():
    book = Book("T", ["Alex Martelli", "Anna Ravenscroft"], "O'Reilly", 2017, "9781449392925")
    assert file_name("{authors} - {title} [{editor}, {isbn}]", book) == \
        "Alex Martelli & Anna Ravenscroft - T [O'Reilly, 9781449392925].pdf"
    book.authors.append("Steve Holden")
    # (no dot before the extension)
    assert file_name("{author} - {authors}", book) == "Alex Martelli - Alex Martelli et al.pdf"


def test_file_name_without_title():
    with pytest.raises(NamingError, match="titre manquant"):
        file_name(PATTERN, Book(authors=["Victor Hugo"], year=2012))
    # a pattern without title
    assert file_name("{author_sort} ({year})", Book(authors=["Victor Hugo"], year=2012)) == \
        "Hugo, Victor (2012).pdf"
    with pytest.raises(NamingError):
        file_name("{author_sort} ({year})", Book())


def test_long_title_is_shortened():
    book = Book(" ".join(["Mot"] * 100), ["Victor Hugo"], year=2012)
    name = file_name(PATTERN, book)
    assert len(name.encode("utf-8")) <= MAX_NAME_BYTES
    assert name.startswith("Hugo, Victor - Mot Mot") and name.endswith(" (2012).pdf")


@pytest.mark.parametrize("name, expected", [
    ("Victor Hugo", "Hugo, Victor"),
    ("Antoine de Saint-Exupéry", "Saint-Exupéry, Antoine de"),
    ("Ludwig van Beethoven", "van Beethoven, Ludwig"),
    ("Martin Luther King Jr.", "King, Martin Luther, Jr."),
    ("Madonna", "Madonna"),
])
def test_author_sort(name, expected):
    assert author_sort(name) == expected


def test_clean():
    assert clean('a/b\\c: "d" <e>|?*\x01  f') == "a-b-c - d e f"
    # composed form (NFC), as typed
    assert clean("Misère") == "Misère"


@pytest.mark.parametrize("pattern", [
    "", "{title}/{year}", "{titre}", "{title:>10}", "{title!r}", "no variable", "{title",
])
def test_invalid_patterns(pattern):
    with pytest.raises(NamingError):
        check_pattern(pattern)


def test_invalid_pattern_refused_at_startup(app, monkeypatch):
    from app import create_app

    monkeypatch.setenv("EBOOKONLINE_FILENAME_PATTERN", "{titre}")
    with pytest.raises(RuntimeError, match="FILENAME_PATTERN"):
        create_app("default")


def test_free_name(tmp_path):
    assert free_name(tmp_path, "a.pdf") == "a.pdf"
    (tmp_path / "a.pdf").touch()
    assert free_name(tmp_path, "a.pdf") == "a (2).pdf"
    (tmp_path / "a (2).pdf").touch()
    assert free_name(tmp_path, "a.pdf") == "a (3).pdf"
    # the file to rename does not count
    assert free_name(tmp_path, "a.pdf", own="a.pdf") == "a.pdf"
    assert free_name(tmp_path, "a.pdf", own="a (2).pdf") == "a (2).pdf"
