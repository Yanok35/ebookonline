import os
from pathlib import Path

from srcs.search import fuzzy_search, normalize

from tests.conftest import make_pdf


class FakeBook:
    def __init__(self, filename):
        self.filename = filename


LIBRARY = [FakeBook(name) for name in [
    "Python Algorithms, 2nd Edition.pdf",
    "Python 3 Text Processing with NLTK 3 Cookbook.pdf",
    "Klaus Iglberger - C++ Software Design_ O'Reilly Media (2022).pdf",
    "Science/Le Petit Élève.pdf",
    "Data Structures.pdf",
    "R in Action.pdf",
]]


def search(query):
    return [os.path.basename(b.filename) for b in fuzzy_search(LIBRARY, query)]


def test_normalize():
    assert normalize("Élève_C++ (2nd-ed).pdf") == "eleve c 2nd ed pdf"
    assert normalize("O'Reilly") == "oreilly"


def test_empty_query_keeps_everything_in_order():
    assert fuzzy_search(LIBRARY, "") == LIBRARY
    assert fuzzy_search(LIBRARY, "  -_ ") == LIBRARY


def test_case_accents_and_punctuation_are_ignored():
    assert search("ELEVE") == ["Le Petit Élève.pdf"]
    assert search("oreilly") == search("O'Reilly") != []
    assert search("software-design") == search("software design") != []


def test_typos():
    # substitution, deletion, insertion, swap of adjacent characters
    assert search("pithon algorithms")[0].startswith("Python Algorithms")
    assert search("algoritms") == ["Python Algorithms, 2nd Edition.pdf"]
    assert search("cookbook") == search("coookbook") != []
    assert search("pyhton algorithms")[0].startswith("Python Algorithms")
    # two typos in a long word
    assert search("procesingg") == ["Python 3 Text Processing with NLTK 3 Cookbook.pdf"]


def test_short_words_need_an_exact_match():
    # no typo allowed up to 2 characters: 'r' must not match everything
    assert search("r") == ["R in Action.pdf"]
    assert search("ib") == []


def test_word_beginning_while_typing():
    assert search("algo") == ["Python Algorithms, 2nd Edition.pdf"]
    # a typo in the beginning of a word being typed
    assert search("algp") == ["Python Algorithms, 2nd Edition.pdf"]


def test_inside_a_word():
    assert search("berger") == ["Klaus Iglberger - C++ Software Design_ O'Reilly Media (2022).pdf"]


def test_all_query_words_are_required_in_any_order():
    assert search("cookbook python") == ["Python 3 Text Processing with NLTK 3 Cookbook.pdf"]
    assert search("python design") == []


def test_ranking_exact_before_typos():
    library = [FakeBook("Pithon Basics.pdf"), FakeBook("Python Basics.pdf"),
               FakeBook("Advanced Python Basics.pdf")]
    names = [b.filename for b in fuzzy_search(library, "python basics")]
    # exact phrase first (in library order), the typo last
    assert names == ["Python Basics.pdf", "Advanced Python Basics.pdf", "Pithon Basics.pdf"]


def test_no_match():
    assert search("xyzzy") == []


def test_bookdir_search(library):
    root = Path(library.dirpath)
    make_pdf(root / "Python Algorithms.pdf")
    make_pdf(root / "Data Science.pdf")
    library.rescan()

    assert [b.filename for b in library.search("pyhton")] == ["Python Algorithms.pdf"]
    # an explicit empty list (e.g. no pinned book) gives no result
    assert library.search("python", []) == []

    # missing books are not searched
    os.remove(root / "Python Algorithms.pdf")
    library.rescan()
    assert library.search("python") == []
