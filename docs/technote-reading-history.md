# Reading history and timeline

The page **Mes lectures** (`/timeline`, linked from the library) shows the
books read by the logged in user along a time line. It is built from the
journal of the reader events, nothing else is stored.

## Journal of the reader events

`reader_events.jsonl` (`READER_EVENTS_FILE`, see `docs/technote-bookdb.md`):
one JSON line per state saved by the reader, `{"t", "doc", "page", "user"}`.
The reader saves its state 500 ms after each move (scroll, page, zoom) and
at the opening of a book. The file is only appended to.

## Sessions (`srcs/users/journal.py`)

- The events of a book, for a user, less than `SESSION_GAP` (10 min) apart
  belong to the same **session**: from its first to its last event, plus
  `SESSION_TAIL` (1 min) for the reading of the last page.
- A page read longer than `SESSION_GAP` without any move ends the session:
  the reader sends nothing meanwhile. A heartbeat of the reader (an event
  every minute while it is visible and used) would make the reading time
  more accurate.
- A malformed line (e.g. truncated by a crash) is skipped and logged; a time
  without timezone is in UTC (the server writes UTC).
- The books no longer in the library (or missing from the book directory)
  are left out of the page.

## Interest of a book

The sum, on its sessions, of `1 + ln(1 + minutes)`: an opening counts, a
long reading more, but 3 hours are not worth 30 short sessions (about 2 for
a session of 2 minutes, 6 for 3 hours).

## The page (`app/templates/timeline.html`)

Drawn in the browser (SVG and the boxes of the library):

- the time line, from the first reading to the latest one (two weeks at
  least), a tick per month;
- along it, a band: the reading time per week;
- the key dates: first reading, the two weeks of most reading (apart from
  the other dates), latest reading;
- the 14 books of most interest, at the middle of their week of most
  interest, sized by their interest, in lanes above and below the line
  (a lane is used only when the book fits). Badge: reading time; caption:
  sessions, reading time, last reading.

The branch `timeline-mockups` keeps the mockups of this page (simulated
data, other variants: key dates, interest of the moment with a half-life).
