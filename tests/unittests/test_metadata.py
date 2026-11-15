"""
Rules of the metadata analysis (srcs/metadata): ISBN, names, publishers,
extraction and analysis of PDF files.
"""

import json

import pytest

from srcs.metadata import analyse, extract, publishers
from srcs.metadata.isbn import find_isbns, isbn13_check, to_isbn13
from srcs.metadata.names import canonical_person, looks_like_person, split_authors
from srcs.metadata.publishers import Publishers, learn_prefixes
from tests.conftest import make_book_pdf

FILLER = [(10, "Lorem ipsum dolor sit amet, consectetur adipiscing elit.")] * 12


def isbn13(prefix12):
    return prefix12 + isbn13_check(prefix12)


# --- ISBN ---

@pytest.mark.parametrize("raw, expected", [
    ("978-2-07-040850-4", "9782070408504"),
    ("9782070408504", "9782070408504"),
    ("2-07-040850-X", None),           # wrong check digit
    ("0-596-10046-9", "9780596100469"),  # ISBN-10 -> ISBN-13
    ("080442957X", "9780804429573"),
    ("9782070408505", None),
    ("", None),
    (None, None),
])
def test_to_isbn13(raw, expected):
    assert to_isbn13(raw) == expected


def test_find_isbns():
    text = "ISBN : 978-2-07-040850-4\nEAN 9780596100469\nTél. 0123456789"
    hits = find_isbns(text)
    assert [(h.isbn13, h.labelled) for h in hits] == [
        ("9782070408504", True), ("9780596100469", False)]
    assert "ISBN" in hits[0].context


# --- names ---

@pytest.mark.parametrize("raw, expected", [
    ("HUGO, Victor", "Victor Hugo"),
    ("VICTOR HUGO", "Victor Hugo"),
    ("Antoine DE SAINT-EXUPÉRY", "Antoine de Saint-Exupéry"),
    ("J.R.R. Tolkien", "J.R.R. Tolkien"),
    ("Mark Lutz (auteur)", "Mark Lutz"),
])
def test_canonical_person(raw, expected):
    assert canonical_person(raw) == expected


def test_split_authors():
    assert split_authors("Alex Martelli & Anna Ravenscroft") == ["Alex Martelli", "Anna Ravenscroft"]
    assert split_authors("Hugo, Victor; Dumas, Alexandre") == ["Victor Hugo", "Alexandre Dumas"]
    assert split_authors("A. One, B. Two, C. Three") == ["A. One", "B. Two", "C. Three"]
    assert split_authors("") == []


@pytest.mark.parametrize("text, expected", [
    ("Victor Hugo", True),
    ("Antoine de Saint-Exupéry", True),
    ("Table des matières", False),
    ("Victor", False),
    ("Chapter 12", False),
    ("Albin Michel", False),  # a publisher
])
def test_looks_like_person(text, expected):
    assert looks_like_person(text) is expected


# --- publishers ---

def test_publishers_file_is_consistent():
    """ Every ISBN prefix of publishers.json names one of its publishers """
    with open(publishers.DEFAULT_FILE, encoding="utf-8") as f:
        data = json.load(f)
    assert set(data) == {"publishers", "isbn_prefixes"}
    assert set(data["isbn_prefixes"].values()) <= set(data["publishers"])
    assert all(p.isdigit() for p in data["isbn_prefixes"])


def test_canonical_publisher():
    ref = Publishers({"O'Reilly": ["O'Reilly Media"], "Stock": ["cs:Stock"]}, {})
    assert ref.canonical("O'Reilly Media, Inc.") == "O'Reilly"
    assert ref.canonical("o'reilly") == "O'Reilly"   # case and accents ignored
    assert ref.canonical("Stock") == "Stock"
    assert ref.canonical("en stock") == "en stock"   # case sensitive alias
    assert ref.canonical("Les Éditions de la Martinière") == "Éditions Martinière"
    assert ref.canonical("Acme Books Ltd") == "Acme Books"


def test_publishers_search_and_prefix():
    ref = Publishers({"Gallimard": ["Éditions Gallimard"], "Seuil": ["cs:Seuil"]},
                     {"978207": "Gallimard"})
    found = dict(ref.search("© EDITIONS GALLIMARD, 1973 — le seuil de la porte"))
    assert list(found) == ["Gallimard"]
    assert ref.by_prefix("9782070408504") == "Gallimard"
    assert ref.by_prefix("9780596100469") is None


def test_learn_prefixes():
    pairs = [("9781617296055", "Manning"), ("9781617296086", "Manning"),
             ("9781484245323", "Apress")]
    learned = learn_prefixes(pairs)
    assert learned["97816172960"] == "Manning"
    # a single book: nothing learned
    assert not any(name == "Apress" for name in learned.values())


# --- extraction and analysis of PDF files ---

@pytest.fixture
def french_book(tmp_path):
    isbn = isbn13("978207040850")
    path = make_book_pdf(tmp_path / "lesmiserables_scan_v2.pdf", [
        [(11, "Victor Hugo"), (26, "Les Misérables"), (12, "Tome I")],
        [(9, "© Éditions Gallimard, 1973, pour la présente édition."),
         (9, "Traduit de l'anglais par Jean Dupont"),
         (9, f"ISBN {isbn[:3]}-{isbn[3]}-{isbn[4:6]}-{isbn[6:12]}-{isbn[12]}"),
         (9, "Dépôt légal : mars 2012"),
         (9, "Achevé d'imprimer en février 2012")],
    ] + [FILLER] * 3, metadata={"title": "Microsoft Word - lesmis.doc", "author": "admin",
                                 "creationDate": "D:20150101000000"})
    return path, isbn


@pytest.fixture
def english_book(tmp_path):
    isbn = isbn13("978059610046")
    path = make_book_pdf(tmp_path / "Alex Martelli - Python in a Nutshell.pdf", [
        [(30, "Python in a Nutshell"), (14, "Alex Martelli")],
        [(9, "Copyright © 2006 O'Reilly Media, Inc. All rights reserved."),
         (9, "Published by O'Reilly Media, Inc., 1005 Gravenstein Highway North."),
         (9, f"ISBN-13: {isbn}")],
    ] + [FILLER] * 3)
    return path, isbn


def suggest_values(path, **kwargs):
    raw = extract.extract(path)
    s = analyse.suggest(analyse.candidates(raw), path.name, **kwargs)
    return {f: v["value"] for f, v in s.items()}, s


def test_extract(french_book):
    raw = extract.extract(french_book[0])
    assert raw["pages"] == 5 and raw["has_text"]
    assert sorted(raw["texts"]) == ["0", "1", "2", "3", "4"]
    assert "Dépôt légal" in raw["texts"]["1"]
    page, lines = raw["fonts"][0]
    assert page == 0 and [26.0, "Les Misérables"] in lines
    assert raw["meta"]["author"] == "admin"
    # saved as JSON in the cache
    assert json.loads(json.dumps(raw)) == raw


def test_extract_key_pages():
    assert extract.key_pages(3) == [0, 1, 2]
    assert extract.key_pages(100) == list(range(15)) + list(range(94, 100))


def test_extract_errors(tmp_path):
    (tmp_path / "bad.pdf").write_bytes(b"not a PDF file")
    with pytest.raises(extract.ExtractError):
        extract.extract(tmp_path / "bad.pdf")


def test_extract_without_text(tmp_path):
    path = make_book_pdf(tmp_path / "scan.pdf", [[]] * 3)
    assert extract.extract(path)["has_text"] is False


def test_xmp_fields():
    xmp = """<x:xmpmeta><rdf:RDF><rdf:Description xmlns:calibre="http://calibre-ebook.com">
      <dc:title><rdf:Alt><rdf:li xml:lang="x-default">Le Petit Prince</rdf:li></rdf:Alt></dc:title>
      <dc:creator><rdf:Seq><rdf:li>Antoine de Saint-Exupéry</rdf:li></rdf:Seq></dc:creator>
      <dc:identifier>urn:isbn:9782070408504</dc:identifier>
    </rdf:Description></rdf:RDF></x:xmpmeta>"""
    fields = extract.xmp_fields(xmp)
    assert fields["dc:title"] == ["Le Petit Prince"]
    assert fields["dc:creator"] == ["Antoine de Saint-Exupéry"]
    assert fields["isbns"] == ["9782070408504"] and fields["calibre"] is True


def test_analyse_french_book(french_book):
    path, isbn = french_book
    values, s = suggest_values(path)
    assert values == {"title": "Les Misérables", "authors": ["Victor Hugo"],
                      "editor": "Gallimard", "year": 2012, "isbn": isbn}
    # the legal deposit wins over the copyright and the file date
    assert s["year"]["sources"][0] == "legal-deposit" and s["year"]["score"] == 100
    assert 1973 in s["year"]["alternatives"]
    # the junk metadata ("Microsoft Word - ...", "admin") and the
    # translator are not candidates
    cands = analyse.candidates(extract.extract(path))
    assert all("Microsoft" not in c[0] for c in cands["title"])
    assert all(c[0] not in ("admin", "Jean Dupont") for c in cands["authors"])


def test_analyse_english_book(english_book):
    path, isbn = english_book
    values, s = suggest_values(path)
    assert values == {"title": "Python in a Nutshell", "authors": ["Alex Martelli"],
                      "editor": "O'Reilly", "year": 2006, "isbn": isbn}
    # also found in the file name
    assert "filename" in s["authors"]["sources"]


def test_analyse_metadata_of_calibre(tmp_path):
    path = make_book_pdf(tmp_path / "book.pdf", [FILLER], metadata={
        "title": "Le Petit Prince", "author": "Antoine de Saint-Exupéry",
        "producer": "calibre 7.0"})
    values, s = suggest_values(path)
    assert values["title"] == "Le Petit Prince"
    assert values["authors"] == ["Antoine de Saint-Exupéry"]
    assert s["title"]["sources"] == ["meta"] and s["title"]["score"] == 45


def test_candidates_do_not_depend_on_the_file_name(english_book, tmp_path):
    path, _ = english_book
    copy = tmp_path / "copy.pdf"
    copy.write_bytes(path.read_bytes())
    assert analyse.candidates(extract.extract(path)) == analyse.candidates(extract.extract(copy))


def test_consolidate_conflict():
    s = analyse.consolidate("year", [[2012, "legal-deposit", 75], [2012, "printed", 45],
                                     [1973, "copyright", 50]])
    assert s == {"value": 2012, "score": 100, "sources": ["legal-deposit", "printed"],
                 "alternatives": [1973]}
    # two serious and different candidates: lower score
    s = analyse.consolidate("year", [[2012, "legal-deposit", 75], [2010, "xmp", 70]])
    assert s["value"] == 2012 and s["score"] == int(75 * 0.7)
    assert analyse.consolidate("year", []) is None


def test_consolidate_similar_titles():
    s = analyse.consolidate("title", [["Python in a Nutshell", "large-font", 30],
                                      ["Python in a Nutshell, 2nd Edition", "meta", 35]])
    assert s["value"] == "Python in a Nutshell" and s["score"] == 65


def test_suggest_with_learned_data():
    cands = {"isbn": [["9781617296055", "isbn", 55]],
             "editor": [["Manning", "isbn-prefix", 40]]}
    # the user spelling replaces the canonical name; the learned prefix
    # replaces the one of publishers.json
    learned = analyse.Learned(prefixes={"97816172": "Manning Publications"},
                              editors={"manning": "Manning Publications"})
    s = analyse.suggest(cands, learned=learned)
    assert s["editor"]["value"] == "Manning Publications"
    assert s["editor"]["sources"] == ["learned-prefix"]


def test_learned_from_books():
    class B:
        def __init__(self, editor, isbn):
            self.editor, self.isbn = editor, isbn

    books = [B("Manning Pubs", "9781617296055"), B("Manning Pubs", "978-1-61729-608-6"),
             B("", "9781484245323")]
    ref = Publishers({"Manning": ["Manning Pubs"]}, {})
    learned = analyse.Learned.from_books(books, ref)
    assert learned.editors == {"manning": "Manning Pubs"}
    assert learned.prefixes["97816172960"] == "Manning Pubs"


def test_filename_candidates():
    assert analyse.filename_candidates("Science/Victor Hugo - Les Misérables [epub].pdf") == {
        "authors": [["Victor Hugo", "filename", 25]],
        "title": [["Les Misérables", "filename", 15]],
    }
    assert analyse.filename_candidates("python_data_science_9781491912058.pdf") == {
        "title": [["python data science", "filename", 15]],
    }


@pytest.mark.parametrize("candidates, expected", [
    # the title page in two font sizes: not cut short
    ([["Python In A Nutshell", "xmp", 50], ["Python", "title-page", 50]], "Python In A Nutshell"),
    # an edition, a subtitle after a punctuation: removed
    ([["Python Cookbook, 2nd Edition", "xmp", 50], ["Python Cookbook", "title-page", 50]],
     "Python Cookbook"),
    ([["Python Algorithms: Mastering Basic Algorithms", "xmp", 50],
      ["Python Algorithms", "title-page", 50]], "Python Algorithms"),
    # most of the title: the rest is an addition
    ([["YouTube Channels For Dummies", "xmp", 50], ["YouTube Channels", "title-page", 50]],
     "YouTube Channels"),
    # a weaker source does not lengthen the title
    ([["Python 3", "large-font", 30], ["Python 3 for Absolute Beginners", "filename", 15]],
     "Python 3"),
    # similar spellings, the same weight: the shortest
    ([["Flutter & Dart Cookbook", "xmp", 50], ["Flutter and Dart Cookbook", "title-page", 50]],
     "Flutter & Dart Cookbook"),
])
def test_consolidate_title_forms(candidates, expected):
    assert analyse.consolidate("title", candidates)["value"] == expected


@pytest.mark.parametrize("title, expected", [
    ("Python Algorithms: Mastering Basic Algorithms",
     ("Python Algorithms", "Mastering Basic Algorithms")),
    ("Les Misérables — Fantine", ("Les Misérables", "Fantine")),
    # a series at the end is left out
    ("Fractional Order Systems: Modeling and Control (World Scientific Series a)",
     ("Fractional Order Systems", "Modeling and Control")),
    # an edition, a volume: not a subtitle
    ("Python for Secret Agents - Second Edition", ("Python for Secret Agents - Second Edition", "")),
    ("Learning Python: 5th Edition", ("Learning Python: 5th Edition", "")),
    ("Les Misérables : Tome 2", ("Les Misérables : Tome 2", "")),
    ("Python Cookbook", ("Python Cookbook", "")),
    ("C++: The Guide", ("C++", "The Guide")),
])
def test_split_title(title, expected):
    assert analyse.split_title(title) == expected


def test_suggest_subtitle():
    cands = {"title": [["Python Algorithms: Mastering Basic Algorithms", "xmp", 50],
                       ["Python Algorithms", "title-page", 50],
                       ["Other Title: Not This One", "meta", 35]]}
    s = analyse.suggest(cands, filename="Python Algorithms - Magnus Lie Hetland.pdf")
    assert s["title"]["value"] == "Python Algorithms"
    assert s["subtitle"]["value"] == "Mastering Basic Algorithms"
    assert s["subtitle"]["sources"] == ["xmp"] and s["subtitle"]["score"] == 50
    # the only title has a subtitle: cut to its title
    s = analyse.suggest({"title": [["Python in Practice: Create Better Programs", "xmp", 50]]})
    assert (s["title"]["value"], s["subtitle"]["value"]) == ("Python in Practice",
                                                            "Create Better Programs")
    # not from the file name, whose parts are often an author
    s = analyse.suggest({"title": [["Python Algorithms", "xmp", 50]]},
                        filename="Python Algorithms - Mastering Basic Algorithms.pdf")
    assert "subtitle" not in s


def test_extract_with_damaged_xmp(tmp_path):
    """
    A low level error of MuPDF (FzErrorFormat "object is not a stream", not
    a RuntimeError) on the XMP metadata: the rest is read
    """
    import pymupdf

    path = make_book_pdf(tmp_path / "book.pdf", [[(24, "Le Petit Prince")]] + [FILLER],
                         metadata={"title": "Le Petit Prince"})
    doc = pymupdf.open(path)
    doc.xref_set_key(doc.pdf_catalog(), "Metadata", "<< /Type /Metadata >>")
    doc.save(tmp_path / "damaged.pdf")
    doc.close()
    with pytest.raises(pymupdf.mupdf.FzErrorBase):
        pymupdf.open(tmp_path / "damaged.pdf").get_xml_metadata()

    raw = extract.extract(tmp_path / "damaged.pdf")
    assert raw["xmp"] == {} and raw["meta"]["title"] == "Le Petit Prince"
    assert "Le Petit Prince" in raw["texts"]["0"]


def test_extract_mupdf_low_level_error(tmp_path, mocker):
    """ Any other low level error of MuPDF: a failed extraction, no exception """
    import pymupdf

    path = make_book_pdf(tmp_path / "book.pdf", [FILLER])
    mocker.patch.object(pymupdf.Document, "page_count", new_callable=mocker.PropertyMock,
                        side_effect=pymupdf.mupdf.FzErrorFormat("object is not a stream"))
    with pytest.raises(extract.ExtractError, match="can not read the PDF file"):
        extract.extract(path)
