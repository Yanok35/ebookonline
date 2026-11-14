# Technical note: the referential of publishers

The metadata analysis (see
[technote-metadata-extract-&-analysis.md](technote-metadata-extract-&-analysis.md))
finds the publisher (the `editor` of a book in `book.db`) with a referential
of known publishers: `srcs/metadata/publishers.json`, read by
`srcs/metadata/publishers.py`. It is delivered with the code, under version
control, and only gives suggestions: nothing is written in `book.db`.

## Uses

1. **Find a publisher in the text** of the key pages (copyright page,
   colophon): each alias of each publisher is searched. Source
   `text-publisher`, weight 35, 45 when the text around has `©`,
   `copyright`, `éditions`, `published`, `ISBN`.
2. **Unify the names**: a publisher written in several ways becomes its
   canonical name, e.g. `O'Reilly Media, Inc.`, `O’Reilly` and `o'reilly`
   all become `O'Reilly`. It applies to every candidate of a publisher
   (XMP `dc:publisher`, `Éditions X`, `Published by X`, `X Press`), and the
   candidates are grouped by canonical name. Without it, the same publisher
   would be suggested in many forms, which would hinder the search and the
   file naming to come.
3. **Find the publisher from the ISBN**, when the text does not name it:
   the longest known prefix of the ISBN-13 of the book gives its publisher.
   Source `isbn-prefix`, weight 40.

## File format

A JSON object with two keys:

```json
{
  "publishers": {
    "O'Reilly": ["O'Reilly Media", "O’Reilly Media", "O'Reilly", "O’Reilly"],
    "Stock": ["Éditions Stock", "cs:Stock"],
    "Le Seuil": ["Éditions du Seuil", "Le Seuil", "cs:Seuil"]
  },
  "isbn_prefixes": {
    "9780596": "O'Reilly",
    "978207": "Gallimard"
  }
}
```

- `publishers`: `{canonical name: [aliases]}`. The canonical name is the
  suggested value.
  - An alias is searched as a whole word (not inside another word),
    ignoring the case and the accents, with any spaces between its words.
  - An alias starting with `cs:` is searched case sensitive: for a name
    which is also a common word (`cs:Stock`, `cs:Pocket`, `cs:Points`), so
    that "en stock" or "Python Pocket Reference" are not taken for a
    publisher.
  - The canonical name is an alias too, unless it is in the list with
    `cs:` (e.g. `"Stock": ["cs:Stock"]`: only `Stock` with this case).
- `isbn_prefixes`: `{prefix: canonical name}`, the prefix being the first
  digits (6 to 12) of the ISBN-13, without separators. The canonical name
  must be one of `publishers` (checked by the tests).

The file is written one publisher per line, to keep the diffs readable.

## Canonical name of a free name

A name which is not in the referential is only cleaned up:

- `Les Éditions de la Martinière` -> `Éditions Martinière` (articles of
  "Éditions de", "du", "des", "de la", "de l'" removed);
- `Acme Books Ltd` -> `Acme Books` (suffixes `Inc`, `Ltd`, `LLC`, `SA`,
  `SAS`, `SARL`, `GmbH`, `Co` removed).

The referential is also used to tell persons from publishers: a name of
publisher (e.g. `Albin Michel`) is never an author candidate.

## Learned from book.db

Two more pieces of information are computed from the values entered by the
user in `book.db` (never from the suggestions), each time suggestions are
made (`analyse.Learned.from_books()`), and never written in the file:

- **User spelling**: the editors entered in `book.db` are grouped by
  canonical name; the most frequent spelling of each group replaces the
  canonical name in the suggestions. If the user writes `Manning
  Publications`, the suggestion is `Manning Publications`, not `Manning`.
- **Learned ISBN prefixes**: from the books having an ISBN and an editor, a
  prefix of 6 to 11 digits is learned when at least 2 books have it and 85%
  of them the same editor (`publishers.learn_prefixes()`). A learned prefix
  replaces the one of `publishers.json` for the book (source
  `learned-prefix`, weight 45).

## Changing the referential

- Edit `srcs/metadata/publishers.json`: add a publisher with its aliases,
  or a prefix.
- Increment `ANALYSER_VERSION` in `srcs/metadata/analyse.py`: the cached
  candidates were found with the previous referential, they are found again
  from the raw data of the cache files, in background, without opening the
  PDF files.
- Run the tests (`tests/unittests/test_metadata.py` checks the file).

A local file, out of the repository, which would extend this referential is
listed in the TODO.

## Origin

The initial content comes from the prototype `ebooktri` (a hundred French
and English publishers, and their collections), with the canonical names
fixed for the `cs:` aliases.
