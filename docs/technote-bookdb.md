# Technical note: the book database (book.db)

The book database keeps the list of books found in the book directory
(`BOOK_DIR`), with the information which can not be found again from the PDF
files themselves: user settings (bookmark, tags, editor, ...) and books whose
file is missing. It is managed by `BookDir` in `srcs/book.py`.

## Location and writes

- Path: `BOOK_DB` setting, `book.db` by default, relative to the current
  directory of the server (see `config.py`; `EBOOKONLINE_BOOK_DB` in the
  environment).
- Format: a JSON object, indented by 2 spaces.
- Writes are atomic: the content is written in a temporary file of the same
  directory, synced, then renamed over `book.db` (`BookDir.save_db()`). An
  interruption can not leave a truncated file.
- The file is written:
  - after each directory scan (at startup, then by the watcher, see
    `BOOK_DIR_WATCH`);
  - when a book is pinned or unpinned (`/pinbook`);
  - when a book is edited in the admin pages (`/bookadmin/<sha1>`);
  - after a migration from an older schema version (see below).

## Schema (version 2)

### Top-level object

| Key                  | Type    | Description |
|----------------------|---------|-------------|
| `version`            | integer | Schema version of the file (`DB_VERSION`). A file without this key is version 0. |
| `min_reader_version` | integer | Oldest schema version whose code can read this file (`DB_MIN_READER_VERSION`). See [Versioning](#versioning). |
| `dirpath`            | string  | Book directory when the file was written. Informative only: not read back, the `BOOK_DIR` setting is used. |
| `booklist`           | array   | The books, see [Book entry](#book-entry). |
| `duplicates`         | array   | The duplicate files, see [Duplicate entry](#duplicate-entry). |

### Book entry

One entry per distinct content (sha1) found in the book directory, including
the books whose file is missing.

| Key          | Type    | Description |
|--------------|---------|-------------|
| `sha1`       | string  | SHA-1 of the file content (40 hexadecimal characters). Identifies the book: a moved or renamed file keeps its entry. Also the name of its thumbnail in the cache (`<sha1>.jpg`). |
| `filename`   | string  | Path of the file, relative to `BOOK_DIR`, with `/` separators. |
| `category`   | string  | First level directory of the file, `Generals` for a file at the root of `BOOK_DIR`. |
| `mtime`      | number  | Modification time of the file (seconds since the epoch, float). `-1` when the file is missing. Recomputed from the file when loaded, see [Known limitations](#known-limitations). |
| `filesize`   | integer | Size of the file in bytes. `0` when the file is missing. Recomputed from the file when loaded. |
| `tags`       | string  | Tags, separated by spaces. `""` when none. |
| `editor`     | string  | Editor. `""` when unknown. |
| `year`       | integer | Publication year. `0` when unknown. |
| `isbn`       | string  | ISBN-10 or ISBN-13, digits (and final `X`) only. `""` when unknown. |
| `bookmarked` | boolean | Pinned book. |

Required when loading: `sha1`, `filename`, `category`. The other keys take
the default value above when missing.

A book whose file is missing is kept, so that its settings are restored if
the file comes back (anywhere in the book directory, with the same content).
It is hidden from the library, and shown as missing in the admin pages.

### Duplicate entry

A file whose content (sha1) is the one of a book, at another path. The book
is the file already known, or the first path in alphabetical order for a new
content; only the book is shown in the library. Duplicates are saved so that
their sha1 is not computed again by each scan.

| Key        | Type    | Description |
|------------|---------|-------------|
| `filename` | string  | Path of the file, relative to `BOOK_DIR`. |
| `category` | string  | First level directory of the file. |
| `mtime`    | number  | Modification time of the file, when its sha1 was computed. |
| `filesize` | integer | Size of the file in bytes. |
| `sha1`     | string  | SHA-1 of the file content: the `sha1` of the book it duplicates. |

### Example

```json
{
  "version": 2,
  "min_reader_version": 1,
  "dirpath": "/srv/ebookonline/books",
  "booklist": [
    {
      "sha1": "122a8eab043565c8d70eba349e330521ea7fb811",
      "mtime": 1794608094.8208742,
      "filename": "R in Action.pdf",
      "category": "Generals",
      "filesize": 6418234,
      "tags": "r statistics",
      "editor": "Manning",
      "year": 2022,
      "isbn": "9781617296055",
      "bookmarked": false
    }
  ],
  "duplicates": [
    {
      "filename": "Downloads/R in Action.pdf",
      "category": "Downloads",
      "mtime": 1794608095.0398746,
      "filesize": 6418234,
      "sha1": "122a8eab043565c8d70eba349e330521ea7fb811"
    }
  ]
}
```

### Schema history

| Version | Changes | `min_reader_version` |
|---------|---------|----------------------|
| 0 | No `version` key. Books with `sha1`, `mtime`, `filename`, `category`, `filesize`, `tags`, `bookmarked`; `editor`, `year` and `isbn` in the most recent files. | — |
| 1 | `version` key added. | — (not written) |
| 2 | `duplicates` added. `min_reader_version` written since then. | 1 |

## Versioning

Two integers describe the schema of a file:

- `version`: the schema version the file was written with. The code knows
  its own version as `DB_VERSION`.
- `min_reader_version`: the oldest schema version whose code reads this file
  correctly. The code writes `DB_MIN_READER_VERSION`.

`min_reader_version` tells an older server whether it can use a file written
by a newer one. It follows the rule of the SQLite read and write version
numbers, or of the ext4 "read-only compatible" features:

- a **compatible** change keeps it unchanged: older code ignores what it
  does not know and still reads the file correctly, e.g. a new key
  (`duplicates` in version 2);
- an **incompatible** change sets it to the new version: older code would
  misread the file, e.g. a key whose type or meaning changes (`tags` becoming
  a list), or a restructuring of the file.

A file without `min_reader_version` can only be read by code of its own
version (or newer).

## Behavior when loading

For a server whose code is at schema version `DB_VERSION` = N, loading a file
of version V (`BookDir.load_db()`, at startup):

| Situation | Behavior |
|-----------|----------|
| No file, or empty file | Empty book list; the file is created by the first scan. |
| V = N | Normal operation. The file is not rewritten by the loading. |
| V < N | Migration: the file is kept as `book.db.v<V>.bak` (only if this backup does not exist yet), converted to version N, then saved at once. Normal operation. |
| V > N, and `min_reader_version` ≤ N | **Read-only** operation, see below. The file is never written. |
| V > N, and `min_reader_version` > N or missing | **Startup refused**: `BookDbVersionError` (the server must be upgraded). The file is left untouched. |

### Migration

Migrations convert the JSON content of the file, version after version:
`_MIGRATIONS[n]` converts a version `n` content to version `n + 1`, so a
version 0 file goes through every migration up to the current version
(`migrate_db()`). The books are then built from the converted content, and
the file is saved in the current version.

The backup `book.db.v<V>.bak` is the file as it was before its first
migration from version V; an existing backup is never overwritten.

### Read-only operation

When the file was written by a newer, compatible, version of the server
(typically a rollback of the server, after its new version migrated the
file):

- the file is loaded as usual, the keys unknown to this version are ignored;
- `BookDir.read_only` is set, and `BookDir.save_db()` writes nothing: the
  file keeps the data of the newer version, which would be dropped by a
  rewrite. No migration and no backup either;
- the directory scan and the watcher still work, in memory: new books are
  shown, their thumbnails generated (the thumbnail cache does not depend on
  the schema);
- pins and book edits are applied in memory only, and lost at the next
  restart;
- a warning is printed at startup, the admin pages show a banner, and the
  book page tells that a change is kept in memory only.

Deploying a server of the file version (or newer) restores the normal
operation.

## Changing the schema

1. Increment `DB_VERSION` in `srcs/book.py`.
2. Append the migration from the previous version to `_MIGRATIONS`: a
   function which takes and returns the JSON content (a dict).
3. If the previous version can not read the new file correctly, set
   `DB_MIN_READER_VERSION` to the new version; otherwise keep it unchanged.
4. Update `load_db()` / `to_json()`, this note (schema and history), and add
   tests: migration from the previous version, and loading by the previous
   version when the change is compatible.

## Known limitations

- **Protection of older servers.** The read-only mode and
  `min_reader_version` are only known by the code which introduced them.
  Code without versioning ignores `version` and would rewrite a newer file,
  dropping what it does not know; code of version 1 to 2 without read-only
  support refuses any newer file.
- **Files modified while the server is stopped.** At loading, the `mtime`
  and `filesize` of a book are taken from the file on disk, not from
  `book.db`. A file replaced by another content while the server is stopped
  is then seen as unchanged by the next scan: its sha1 (and thumbnail) are
  not updated. Files modified while the server runs are detected.
- **One process per book directory.** Each process keeps its own book list in
  memory and rewrites the whole file: the server must run a single process
  (e.g. gunicorn `-w 1`).
- **Reader states** (`reader_states.json`, `STATE_FILE`) are a separate file,
  which is not versioned.
