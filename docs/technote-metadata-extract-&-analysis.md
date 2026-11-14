# Technical note: metadata extraction and analysis

The server reads the PDF files of the books to suggest their metadata to the
user: title, authors, editor (publisher), year, ISBN. The suggestions
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
3. the best group gives the suggestion, its best value (the shortest form
   among the best ones for a title);
4. **conflict**: when the second group scores at least 80% of the first
   one, the score is lowered by 30%.

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
  a request marked urgent (e.g. "Relancer l'analyse" on the book page,
  phase 2) goes first;
- `METADATA_WORKERS` worker processes (1 by default), at the nice level
  `METADATA_NICE` (10 by default), make the cache files up to date
  (`store.update()`). A worker only gets a sha1 and a path and writes one
  file: several of them can run;
- a book taking more than 5 minutes is stopped, and saved as failed;
- a worker which dies (e.g. a crash of MuPDF on a malformed file) is
  restarted, and its book saved as failed;
- the workers are started by `forkserver` (not forked from the server,
  which has threads), and exit with the server.

| Setting | Default | Description |
|---------|---------|-------------|
| `METADATA_ANALYSIS` | `True` | Run the background analysis |
| `METADATA_WORKERS` | `1` | Number of worker processes |
| `METADATA_NICE` | `10` | Nice level of the workers (0: same priority as the server) |

When the cache directory can not be written (`Cache.writable`, see the
read-only mode in `technote-bookdb.md`), nothing runs; the existing cache
files are still read. In the other read-only cases, the cache files are
written, like the thumbnails: they do not depend on `book.db`.

Order of magnitude: about 0.15 s per book on a desktop computer, one
process.

## Known limitations

- No OCR: a scan without text layer only has its file name and its
  metadata as sources.
- The rules are tuned for French and English books. Spanish or Portuguese
  compound surnames, re-editions (the year is the one of the owned edition,
  not of the first publication), books without ISBN or title page are
  often wrong or incomplete: the user review is needed.
- A worker which dies while its task is waiting in the queue (not yet
  started) leaves this book pending until the server restarts.
