# Technical note: metadata extraction and analysis

The server reads the PDF files of the books to suggest their metadata to the
user: title, subtitle, authors, editor (publisher), year, ISBN. The suggestions
prefill the forms of the admin pages, for the user to review, complete or
validate. **Nothing is written in `book.db` without the user**: the
suggestions are kept in the cache directory only.

Code: `srcs/metadata/`. The rules come from the prototype `ebooktri`.

| Module | Role |
|--------|------|
| `extract.py` | Raw data read from a PDF file (PyMuPDF) |
| `analyse.py` | Candidate values found in the raw data, and their consolidation into suggestions |
| `store.py` | Cache file of a book, made up to date when needed |
| `service.py` | Background processes which keep the cache files up to date |
| `isbn.py`, `names.py`, `publishers.py`, `text.py` | Rules: ISBN, names of persons, referential of publishers (see [technote-metadata-publisher.md](technote-metadata-publisher.md)), text helpers |

## Overview

```
 PDF file ──extract()──> raw data ──candidates()──> candidates ─┐
 (once per content)       (cache)                   (cache)     │
                                                                 ├─suggest()──> suggestions
 file name ──filename_candidates()──────────────────────────────┤  (on request, not saved)
 book.db (user values) ──Learned.from_books()───────────────────┘
```

1. **Extraction** (`extract.extract()`): the PDF file is opened once, and
   only its key pages are read.
2. **Candidates** (`analyse.candidates()`): every value found for each
   field, with its source and a weight.
3. **Suggestions** (`analyse.suggest()`): the candidates of each field are
   consolidated into one suggestion, with a score. They are computed when
   needed (e.g. for the book page), from the cache file, the current file
   name and what is learned from `book.db`: these two can change at any
   time, they are not saved.

## Extraction

For each PDF file:

- the **metadata of the document** (Info dictionary: title, author,
  producer, creation date, ...), keys in lower case;
- its **XMP metadata**: `dc:title`, `dc:creator`, `dc:publisher`,
  `dc:date`, `dc:identifier`, ..., the ISBN found anywhere in it, and
  whether it was written by calibre;
- the **text of the key pages**: the first 15 and the last 6 pages (title
  page, copyright page, colophon, "achevé d'imprimer");
- the **lines of the first 4 pages with their font size**: the title is
  usually the largest text of the title page.

A document whose key pages have less than 200 characters of text has no
usable text layer (a scan without OCR): `has_text` is false. A file which
can not be opened (not a PDF file, damaged, encrypted with a password) is an
error.

## Candidates

A candidate is `[value, source, weight]`: the weight tells how much this
source is trusted. Main sources and weights:

| Field | Source | Weight |
|-------|--------|--------|
| title | XMP `dc:title` | 50 |
| title | Info title | 35 (45 for calibre) |
| title | largest font of the title page, with names of persons on the page | 50 (30 without names) |
| title | file name | 15 |
| subtitle | lines under the title of the title page, with names of persons on the page | 40 (25 without names) |
| authors | XMP `dc:creator` | 50 |
| authors | names of persons of the title page | 50 |
| authors | Info author | 35 (45 for calibre) |
| authors | name after `©` | 35 |
| authors | "par / by X" line, file name `Author - Title` | 25 |
| authors | name alone on a line of the first pages | 8 |
| editor | XMP `dc:publisher` | 50 |
| editor | known publisher named in the text | 35 to 45 |
| editor | "Published by X", "Éditions X", "X Press" | 25 to 35 |
| editor | ISBN prefix (learned / `publishers.json`) | 45 / 40 |
| year | "Dépôt légal" | 75 |
| year | XMP `dc:date`, "©" (latest year) | 50 |
| year | "Achevé d'imprimer" | 45 |
| year | "First published", "Première édition" | 20 |
| year | creation date of the file | 8 |
| isbn | labelled ISBN ("ISBN ..."), bare EAN-13 number | 30, 12, plus 20 on a copyright page, ... |

Some details of the rules:

- **ISBN**: the check digit is verified, an ISBN-10 is converted to
  ISBN-13. An ISBN of a page listing more than 3 ISBN (catalog) weighs
  much less, one of a page "Du même auteur", "Also by" less. The context
  (digital or printed edition) adds a little.
- **Names**: `HUGO, Victor` and `VICTOR HUGO` become `Victor Hugo`.
  Headings ("Table des matières"), publishing words and publishers are
  not names. The translators ("Traduit par X", "Translated by X") are
  excluded.
- **Junk metadata**: values written by software ("Microsoft Word - ...",
  "admin", "untitled", "Adobe ...") are ignored. calibre is detected, and
  its metadata, usually reliable, weighs more.
- **Text dates**: only the pages looking like a copyright page or a
  colophon (`©`, `ISBN`, "Dépôt légal", "All rights reserved", ...) are
  searched for years and publishers.

The candidates only depend on the content of the PDF file; the file name
is a source too, but its candidates are found when suggestions are made
(`analyse.filename_candidates()`): a renamed file keeps its cache file.

## Suggestions

For each field (`analyse.consolidate()`):

1. the candidates are grouped: same value, or similar one (same words in
   another order for the names, a title which starts another one, close
   spelling, same canonical name for the publishers);
2. a group **scores the sum of the best weight of each of its sources**, up
   to 100: several independent sources which agree make a reliable value;
3. the best group gives the suggestion, its best value (for a title, see
   below);
4. **conflict**: when the second group scores at least 80% of the first
   one, the score is lowered by 30%.

For a title, among the values of the best sources (80% of the best weight)
of the group (`shortest_title()`):

- a shorter form is kept when what it removes is an addition: after a
  punctuation (`Python Cookbook, 2nd Edition` -> `Python Cookbook`,
  `Python Algorithms: Mastering ...` -> `Python Algorithms`), or when it
  keeps at least half of the title (`YouTube Channels For Dummies` ->
  `YouTube Channels`);
- a title cut short is not kept: `Python` of `Python In A Nutshell`, when
  the title page has the title in two font sizes;
- similar spellings of the same weight: the shortest one;
- the weaker sources (the file name) never lengthen a title: they often
  add a subtitle, an author or a publisher.

The **subtitle** comes from two sources, used only when their title is the
suggested one (`analyse.subtitle_candidates()`):

- the title candidates made of a title and a subtitle
  (`analyse.split_title()`), after `: ` or a dash between spaces:
  `Python Algorithms: Mastering Basic Algorithms in the Python Language`
  gives the subtitle `Mastering Basic Algorithms in the Python Language`,
  with the source and the weight of this candidate. A series at the end in
  parentheses (`(World Scientific Series ...)`) is left out; an edition or
  a volume (`- Second Edition`, `: Tome 2`) is not a subtitle. The file
  name is not used: its parts are often an author or a publisher;
- the title page (`analyse.title_page_subtitle()`, cached candidates): the
  lines just after the title, in a single smaller font size, an edition
  between them skipped ("Second Edition"). It ends at a name of person, a
  separator (`—`), a publisher, a city ("BIRMINGHAM - MUMBAI"), a web
  site; a line ending with a lowercase word or a comma is continued by the
  next one, even if it looks like a name (`Mastering Basic Algorithms in
  the` / `Python Language`), and the lines of the subtitle are not taken
  for authors. The end of the title in a smaller size (`Python` / `In A
  Nutshell`) is not a subtitle. The taglines of some publishers ("Over 80
  recipes to ...") are found as subtitles: they are often long, but their
  words help the search.

A suggested title made of a title and a subtitle is cut to its title, the
subtitle having its own field. The two sources agree on the same subtitle
for most books which have both (`Python Algorithms`: XMP and title page,
score 90).

For the authors, every name scoring at least 75% of the first one (and 30)
is kept, 4 at most.

A suggestion is:

```json
{"value": "Victor Hugo", "score": 75, "sources": ["title-page", "filename"],
 "alternatives": ["Jean Dupont"]}
```

`value` is a list of names for the authors, an integer for the year, an
ISBN-13 for the ISBN. `sources` are the sources of the value, best first
(their labels for the user are `analyse.SOURCE_LABELS`). `alternatives` are
the values of the next groups, 3 at most.

Then the values entered by the user in `book.db` refine the editor
suggestion: their spelling of a publisher, and the ISBN prefixes they
teach (see the publishers note).

## Cache file

`CACHE_DIR/<sha1>.meta.json.gz`, next to the thumbnail `<sha1>.jpg`: a JSON
object compressed with gzip, written to a temporary file then renamed.

| Key | Description |
|-----|-------------|
| `sha1` | SHA-1 of the PDF file |
| `extract_version` | `EXTRACT_VERSION` of the code which read the PDF file |
| `analyser_version` | `ANALYSER_VERSION` of the code which found the candidates (`null` on error) |
| `extracted_at`, `analysed_at` | Dates, ISO 8601, UTC |
| `error` | Why the PDF file could not be read, or `null` |
| `raw` | Raw data of the PDF file (`{}` on error) |
| `candidates` | `{field: [[value, source, weight]]}` (`{}` on error) |

It stores on the disk the metadata extracted from a PDF file, to prepare
the suggestions shown to the user. It does not contain the suggestions
themselves (computed on request), nor the user values (`book.db`).

Its content only depends on the content of the PDF file: identified by the
sha1, a moved or renamed book keeps it, and a cache directory can be copied
from another computer. It can be removed at any time, it is made again.
About 10 KB per book (22 KB at most on a library of technical books).

### Versions

Two numbers tell whether a cache file is up to date with the code:

- `EXTRACT_VERSION` (`extract.py`): incremented when other data is read
  from the PDF files (e.g. more pages). The older files are extracted again:
  every PDF file is opened again.
- `ANALYSER_VERSION` (`analyse.py`): incremented when the rules of the
  candidates change (rules, weights, `publishers.json`). The candidates of
  the older files are found again from their raw data, without opening the
  PDF files: fast, the reason why the raw data is kept.

There is no migration: an outdated file is made again, in background.
`suggest()` runs on each request, it has no version.

A failed file (error) is not tried again until `EXTRACT_VERSION` changes:
a damaged file is not opened at each start.

## Background processing

`MetadataService` (`service.py`), created by `create_app()`
(`app.metadata`) and started with the directory scan:

- each scan asks for the analysis of every present book
  (`BookDir.metadata.request()`, next to the thumbnail request); a book
  known up to date is skipped, so only the first scan of the server reads
  every cache file;
- the server process keeps the queue of the books, in a dispatcher thread;
  a request marked urgent ("Relancer l'analyse" on the book page) goes
  first;
- a pool of `METADATA_WORKERS` worker processes (1 by default, 0 for half
  of the processors), at the nice level `METADATA_NICE` (10 by default),
  make the cache files up to date (`store.update()`). A worker only gets a
  sha1 and a path and writes one file, so the workers share nothing but the
  queue: the dispatcher feeds a queue bounded to one task per worker, so
  that an urgent request waits for one task per worker at most;
- a book taking more than 5 minutes is stopped, and saved as failed;
- a worker which dies on a book (e.g. a crash of MuPDF on a malformed
  file) is restarted at once, and its book saved as failed;
- a worker which dies without processing a book (e.g. at its start, by an
  error of configuration) is restarted after 1, 2, 4, ... seconds, 60 at
  most, not in a loop; the delays start again from 1 s once it has
  processed a book;
- the workers are started by `forkserver` (not forked from the server,
  which has threads), and exit with the server.

| Setting | Default | Description |
|---------|---------|-------------|
| `METADATA_ANALYSIS` | `True` | Run the background analysis |
| `METADATA_WORKERS` | `1` | Number of worker processes, 0 for half of the processors |
| `METADATA_NICE` | `10` | Nice level of the workers (0: same priority as the server) |

When the cache directory can not be written (`Cache.writable`, see the
read-only mode in `technote-bookdb.md`), nothing runs; the existing cache
files are still read. In the other read-only cases, the cache files are
written, like the thumbnails: they do not depend on `book.db`.

Order of magnitude, on a desktop computer (8 processors), 106 technical
books:

| Workers | Time | Per book |
|---------|------|----------|
| 1 | 9.1 s | 0.09 s |
| 2 | 5.0 s | 0.05 s |
| 4 | 3.0 s | 0.03 s |
| 7 | 3.0 s | 0.03 s |

Only the first start of a server on a large library analyses every book;
then only the new ones. Each worker reads one PDF file at a time, at most
21 pages, and only their text (the images of the pages are not loaded):
about 80 MB of private memory per worker at most on this library (300 MB
when the images of the title pages were loaded).

## Book page (`/bookadmin/<sha1>`)

The suggestions are made when the page is shown (`app/admin/metadata.py`),
from the cache file of the book, its file name, and what is learned from
the other books of `book.db`. Nothing is saved until the user submits the
form.

- **Empty field**: prefilled with the suggestion, highlighted (yellow), the
  score and the sources below it. Saving the form validates it. A field
  edited by the user is no longer highlighted.
- **Field with a value**: never replaced. When the suggestion is another
  value (compared without case and accents; same publisher; same ISBN as
  ISBN-13), a hint shows it, with a button "Utiliser" which sets it in the
  field.
- **Reviewed book** (`meta_reviewed`, badge "relu"): nothing is prefilled,
  an empty field only gets the hint and "Utiliser": the user chose to leave
  it empty.
- The alternatives of a field are proposed in its list (datalist); the
  other names of persons found, as buttons "+ name" adding an author.
- Buttons: "Enregistrer" (keeps the review state), "Enregistrer et marquer
  comme relu", and on a reviewed book "Enregistrer et remettre à relire".
  The authors are entered one per line (or separated by ";").
- **Analyse du PDF**: the state of the analysis (pending, date, no text,
  error, done by an older version), and "Relancer l'analyse": the PDF file
  is read again (`force`), before the other books. While the analysis is
  pending, the page asks `/bookadmin/<sha1>/analysis` (JSON `{"pending":
  bool}`) every 2 seconds, and reloads when it is done, unless the form was
  edited meanwhile (then it only tells it).
- **Détail de l'analyse** (bottom of the page): every candidate of each
  field, with its source and weight, and the text extracted from the key
  pages: to understand a wrong suggestion.

## Reader (`/reader/<sha1>`)

While the metadata of a book is not reviewed (`meta_reviewed` false), the
toolbar of the reader shows a badge "À relire" (only its icon on a narrow
screen), a link to the book page, opened in a new tab so that the reading
goes on. It is not shown by the deprecated route `/pdfjsviewer/...`.

## Command line (`app/cli.py`)

`flask --app ebookonline metadata ...`, with the configuration of the
server, without starting its services (book.db is only read):

- `scan`: analyses the present PDF files whose cache file is missing or
  outdated (internal errors included), or all of them (`--force`), or the
  given ones, in `--jobs` processes at the `--nice` level, with the same
  timeout and error handling as the service (`service.analyse_book()`).
  The files are listed from the book directory (`BookDir.pdf_files()`):
  only the files unknown to book.db (path and modification time) are
  hashed. **Initial analysis of a large library on another computer**: on
  a copy of the library (book.db is not needed), set `BOOK_DIR` and
  `CACHE_DIR`, run `scan --jobs N`, then copy the `*.meta.json.gz` files
  to the cache directory of the server: they are named after the content
  of the PDF files, not their paths, and the server finds them up to date
  (same `EXTRACT_VERSION` and `ANALYSER_VERSION`).
- `show BOOK`: the values of book.db, the suggestions (score, sources,
  alternatives) and the candidates (weight, source) of a book, by sha1 or
  path (also a file unknown to book.db). The candidates are found again
  from the cached raw data with the rules of the running code: a change
  of the rules is seen at once (`--json`, `--text` for the extracted
  text).
- `stats`: the state of the cache files, and per field the books filled
  in book.db, the books with a suggestion, and **on the reviewed books, how
  often the suggestion is the value of book.db** (overall, and with a
  score of 80 or more). `--live` finds the candidates again with the rules
  of the running code.

**Tuning the rules**: change `srcs/metadata/` (or `publishers.json`), check
a few books with `show`, compare `stats --live` with `stats`, then
increment `ANALYSER_VERSION` so that the cache files are updated (from
their raw data, by the server or by `scan`). The editor spellings learned
from book.db include the reviewed books themselves: the agreement of the
editor is a little optimistic.

## Known limitations

- No OCR: a scan without text layer only has its file name and its
  metadata as sources.
- The rules are tuned for French and English books. Spanish or Portuguese
  compound surnames, re-editions (the year is the one of the owned edition,
  not of the first publication), books without ISBN or title page are
  often wrong or incomplete: the user review is needed.
- A worker which dies while its task is waiting in the queue (not yet
  started) leaves this book pending until the server restarts.
