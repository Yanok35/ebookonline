# The data of the users: `userdata.db`

The data kept by the server for each user, found again in any browser, on
any device: the notes in the margin of the books, the reading positions,
the pins. A JSON file next to
`book.db`, on the same principles (versioned, kept in memory, rewritten
whole and atomically after each change). Code: `srcs/users/userdata.py`.

## Location

`USERDATA_DB` setting, `userdata.db` in the current directory by default
(e.g. `EBOOKONLINE_USERDATA_DB=/var/lib/ebookonline/userdata.db`). Data of
the users, which can not be made again: not in `CACHE_DIR`; to back up with
`book.db`. Its directory is checked at startup as the other ones (read-only
mode when it can not be written, see `docs/technote-bookdb.md`).

## Schema (version 2)

```json
{
  "version": 2,
  "min_reader_version": 1,
  "users": {
    "<login>": {
      "states": {
        "<sha1 of the book>": {
          "documentId": "<sha1 of the book>",
          "documentName": "Dune.pdf",
          "pageNumber": 12,
          "positionX": 0,
          "positionY": 120.5,
          "zoom": 1.25,
          "updatedAt": "2026-11-25T10:05:00.000Z"
        }
      },
      "pins": ["<sha1 of a book>"],
      "notes": {
        "<sha1 of the book>": [
          {
            "id": "n-mi3k2a9f",
            "page": 12,
            "ratio": 0.42,
            "quote": "selected text, 256 characters at most",
            "text": "text of the note",
            "created": "2026-11-25T10:00:00Z",
            "updated": "2026-11-25T10:05:00Z"
          }
        ]
      }
    }
  }
}
```

- `users`: by login of the user (`current_user_key()`, `app/auth.py`: the
  only place to change to key them otherwise, e.g. by an id). The logins of
  `CREDENTIALS` are checked at startup: letters, digits, `.`, `_`, `@`, `-`.
- a note: `page` (from 1) and `ratio` (height in the page, 0 to 1) anchor
  it; `quote` the text selected when it was made (empty if none); `text`
  its text (10 000 characters at most); `created` and `updated` (UTC, time
  of the server) set by the server. 1 000 notes at most per book; a note
  without quotation nor text is not kept, nor a book without notes.
- `states`: the reading position of the user in each book (as sent by the
  reader, `PUT /api/reader/state`); `pins`: the books pinned by the user.

### Schema history

| version | change | min_reader_version |
|---|---|---|
| 1 | `notes` of each user | 1 |
| 2 | `states` and `pins` of each user (older code keeps them: the users are kept as they are) | 1 |

## Positions and pins of before: copied once

The reading positions (`reader_states.json`, `STATE_FILE`) and the pins
(`bookmarked` of `book.db`) were common to all the users. At startup
(`import_common_data()`, `app/api.py`), each user of `CREDENTIALS` who has
no `states` nor `pins` yet gets a copy of them (also a user added later).
Then those sources are no longer written: kept as they are (a backup, and
an older version can still run on them). Not done when `reader_states.json`
can not be read (done at a next start). In read-only mode, the copy is in
memory only.

## Versioning

As `book.db`: `USERDATA_VERSION` and `USERDATA_MIN_READER_VERSION` in
`srcs/users/userdata.py`, the migrations in `_MIGRATIONS` (`_MIGRATIONS[n]`
converts version `n` to `n + 1`). A file of a newer version is read and
never written: the notes are then kept in memory only, and the server is in
read-only mode (one more reason in the list); it is refused when its
`min_reader_version` is newer than this code.

## API (`app/api.py`, `app/main.py`)

- `GET /api/reader/state/<sha1>`, `PUT /api/reader/state`: the reading
  position of the logged in user (also appended to the journal of the
  reader events);
- `POST /pinbook` (`id`: sha1): pins or unpins a book for the logged in
  user; the library shows their pins, and the filter "épinglés" of the
  search keeps them;
- `GET /api/notes/<sha1>`: `{"notes": [...]}`, the notes of the logged in
  user on this book;
- `PUT /api/notes/<sha1>`: `{"notes": [{id, page, ratio, quote, text}]}`, all
  the notes of the user on this book, with the CSRF token of the reader page
  in the `X-CSRFToken` header; answers the notes as kept, or `{error}` with
  400 (invalid token or notes), 404 (unknown book), 500 (not written). In
  read-only mode: kept in memory, lost at the restart.

The reader saves them 500 ms after a change, and when the page is left.
While the server can not save them, a copy is kept in the browser
(`localStorage`), sent at the next opening (also the notes of the mockup,
kept in the browser only).

Two tabs on the same book: the last saving wins (the whole list).

## Life of the book

The data is keyed by the sha1 of the book. When its file is replaced in
place (cover page, optimization, restored original: `BookDir.transform()`,
`restore_original()`), the notes, reading positions and pins of the users
follow it (`move_user_data()`, `app/api.py`), the pages moved as the pages
of the book. A book in the trash keeps them (the same sha1 when it comes
back); the copies of a book (duplicates) share them.

## User identity

The login is the identity of the user (decided): in the session, the
journal of the reader events (`"user"`), `userdata.db`, the logs (fail2ban
reads the failed logins). Introducing user ids (renaming a login without
losing their data, no name in the data) would need: a new format of
`CREDENTIALS`, the lines of `reader_events.jsonl` translated at reading (the
journal is never rewritten), a migration of `userdata.db` (keys renamed,
from a table login -> id of the configuration), a new login of the users.
Nothing for `reader_states.json`, `book.db`, `CACHE_DIR`.

| | keep the login | user ids |
|---|---|---|
| work | none | configuration, session, journal, tests |
| migration in production | none | `CREDENTIALS`, journal, new login |
| rename a user | migrate all their data | change the login in the configuration |
| key in the data | checked (allowed characters) | safe by construction |
| name in the data (backups, copies) | yes | no (opaque id) |
| reading the data when debugging | direct | through the table login -> id |
| risk | low | medium (consistency id <-> login) |
