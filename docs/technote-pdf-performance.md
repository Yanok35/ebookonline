# PDF files and the performance of the reader

Why some books are slow to open in the reader (pdf.js), which parts of a
PDF file can be measured, and what can be optimized or cached. Measures
made on a book of 80.9 MB (377 pages, made by WeasyPrint), with the
reader of the server, Chrome, and a link limited to 20 Mbit/s (the
upload of a home server).

## Structure of a PDF file

- **Header** (`%PDF-1.7`), then a **body** of numbered *objects*:
  dictionaries, arrays, numbers, strings, and *streams* (a dictionary and
  binary data, usually compressed: `/FlateDecode` (zip), `/DCTDecode`
  (JPEG), ...).
- **Cross-reference table** (or xref stream): the offset of each object in
  the file, then a **trailer** pointing to the root. Objects may be
  grouped in compressed *object streams* (`/ObjStm`). An edited file may
  have *incremental updates*: new objects and xref appended at the end.
- **Document catalog** (the root): the **page tree**, the **outline**
  (bookmarks), names, the **metadata** (Info dictionary, XMP stream).
- **Page**: a size (MediaBox), one or more **content streams** (the
  drawing operators: text, paths, `Do` to draw an image or a form), and
  **resources**: the fonts, images and forms (*XObjects*), graphic
  states, colour spaces, patterns the content uses by name. A resource
  dictionary may be **shared** by several pages. Also annotations
  (links, forms, comments).
- **Fonts**: embedded font programs (TrueType, CFF, Type 3), usually
  *subsets* (the glyphs used only).
- **Images**: width, height, colour space (Gray, RGB, CMYK, ICC),
  compression, an optional soft mask (transparency).
- **Linearization** ("fast web view"): the objects of the first page at
  the beginning of the file, with a hint table, to show it before the
  whole file is read.

## What makes the reader slow

The reader asks for the PDF file by ranges of 64 KB (`disableAutoFetch`,
range requests), so as to read only what it needs. But before drawing a
page, pdf.js loads **every resource the page declares**
(`Page.loadResources()`, `ObjectLoader`), images included, drawn or not.

The book measured shares one resource dictionary between its pages
(WeasyPrint): from page 2, each page declares the **238 images of the
book (77.7 MB)**, while it draws 0 or 1 of them. Opening the book
downloads tens of MB before the first page is shown:

| | first page | requests | downloaded | page 100 |
|---|---|---|---|---|
| original, 20 Mbit/s | 11.0 s | 197 | 21.9 MB | 22.8 s |
| per-page resources, 20 Mbit/s | 1.7 s | 12 | 0.7 MB | 0.2 s |
| original, no limit | 2.3 s | 244 | 39.9 MB | 0.2 s |
| per-page resources, no limit | 0.6 s | 13 | 2.4 MB | 0.7 s |

"Per-page resources": a copy where each page declares only the images it
draws (MuPDF `page.clean_contents(sanitize=True)`, then saved with
`garbage=3`): same pages, same rendering, 80.3 MB, made in 1 s.

The rendering itself is not the problem here: MuPDF draws a page of this
book in 1 to 36 ms (151 ms for the cover, a CMYK JPEG of 2325×2850).

## Indicators (proposal: a `<details>` of the book page)

Measurable with PyMuPDF when the file is read (no rendering needed, a few
hundred ms for a large book), kept in the cache like the metadata
analysis:

| indicator | why |
|---|---|
| size, pages, PDF version, producer | context (WeasyPrint, scanners, ... have their habits) |
| linearized, incremental updates, object count | opening without reading the whole file |
| bytes by kind: images, fonts, content, other | where the weight is |
| images: count, total, largest (pixels, MB), compression, colour spaces, soft masks, CMYK | decoding cost in the browser (CMYK and JPX are slow in pdf.js) |
| fonts: count, embedded, subsets, Type 3 | Type 3 fonts are drawn as paths: slow |
| content streams per page: median, largest | many operators: slow pages (plans, charts) |
| **resources declared per page: largest, and their bytes** | **what pdf.js downloads before drawing a page**: the main cause found |
| outline entries, annotations | |

With warnings when a threshold is passed, e.g. "shared resources: a page
needs 77.7 MB before being shown", "CMYK images", "not linearized and
larger than 50 MB".

## Optimizations of the file

1. **Per-page resources** (lossless): the large gain on books made by
   WeasyPrint and some other tools; same pages, same rendering. MuPDF
   rewrites the content streams (sanitize): to check on a few books.
2. **Unused objects removed, streams compressed, object streams**
   (`garbage=3`, `deflate`): a few % of size.
3. **Linearization** (`qpdf --linearize`; MuPDF no longer writes it): the
   first page read first; a small gain once the resources are per page.
4. **Images** (lossy, optional): downsampled above what the page shows
   (e.g. 200 dpi at the size of the page), screenshots kept lossless,
   photos in JPEG, CMYK converted to RGB. Divides the size by 2 to 5 on
   some books, but changes their content.

Changing a file of the library changes its sha1, the identity of the
book: book.db (user values), reader states, journal of the reader events,
thumbnail and metadata cache are keyed by it. An optimization in place
needs to move them to the new sha1 (as the copy with a cover page copies
the user values), and to keep the original (in the trash).

## Caches

1. **Optimized copy in the cache, served to the reader** (recommended
   first step): `CACHE_DIR/<sha1>.reader.pdf`, made in the background
   (as the metadata analysis) only when worth it (e.g. a page declares
   more than 10 MB of resources). `/pdf/<sha1>` serves it to the reader,
   the download button serves the original.
   - the book keeps its sha1: nothing to move; same pages and page sizes:
     the reading positions, notes and history stay valid;
   - cost: the disk space of the copies (about the size of the books
     concerned), the CPU of the background work, a removal of the copies
     of removed books;
   - invalidation: none needed, the copy is keyed by the sha1 of its
     original, and by a version of the optimization.
2. **HTTP cache of `/pdf/<sha1>`**: a URL keyed by the content never
   changes; `Cache-Control: private, max-age=31536000, immutable` lets
   the browser reuse the ranges already downloaded when a book is opened
   again (to check: today only `ETag` / `Last-Modified` are sent).
3. **Larger ranges** (`rangeChunkSize` 256 KB to 1 MB instead of 64 KB):
   fewer requests (244 here), a gain on a link with latency; HTTP/2 on
   the reverse proxy helps likewise.
4. Not recommended: pages rendered by the server (images per page and
   zoom: much disk, no text layer, the reader to rewrite).

## Transformations of a book file

The optimization is the first operation which changes the content of a
file of `BOOK_DIR`, but not the only one: the insertion of a cover page
(today a copy, `name (covered).pdf`, a new book with the user values of
the original) is another transformation of the content. Both use one
general operation of the book directory.

### A transformation

A transformation is described by:

- `apply(src, dst)`: writes the new file (PyMuPDF);
- the **page mapping**: old page → new page. The identity for the
  optimization; `n → n + 1` for a cover page added before the first one;
- what it **keeps**: the first page (then the thumbnail is kept), the text
  of the pages (then the metadata analysis is kept), the pages themselves
  (then the reading positions and the notes stay valid, once mapped);
- its **checks** of the new file: same number of pages (or one more for
  a cover), same page sizes, same text, the rendering of a few pages
  compared at low resolution.

Two **modes**:

- **copy**: the new file next to the original (`name (covered).pdf`), a
  new book with the user values of the original; nothing else changes
  (today's cover page);
- **replace**: the new file takes the place of the original, which goes
  to the Trash; the book keeps its entry, its path, its user values and
  its data, under its new sha1.

### `BookDir.transform(sha1, transformation, mode)`, under the scan lock

1. the book: present, without duplicates (see below);
2. `apply()` into a hidden temporary file next to the original (ignored by
   the scan and the watcher); the checks; its sha1 (already known: a copy
   of another book, refused);
3. *copy*: move to a free name, a new entry with the user values;
   *replace*: the original to the Trash, the new file to its path;
4. *replace*: the entry takes the new sha1, size and mtime; the data
   keyed by the sha1 follow it (next section);
5. save book.db: the watcher then finds nothing to do (book.db already
   has the size and mtime of the file).

The data kept outside of book.db (reading positions, notes) belong to the
application (`app/`), not to the book directory: the operation returns
what changed (old sha1, new sha1, page mapping, what is kept), the
application moves its data under its own locks.

## Consequences of a replacement, and their mitigations

| place | without care | mitigation |
|---|---|---|
| book.db: user values | kept (the rescan sees "same path, new content") | done by the operation, not by a later rescan |
| duplicates of the book | broken: the entry may follow a copy ("moved"), the new file becomes a book without user values | **refused** while the book has duplicates |
| thumbnail `<sha1>.jpg` | made again, the old one orphan | **renamed** when the first page is kept (optimization), **made again** otherwise (cover); the old one removed |
| metadata analysis `<sha1>.meta.json.gz` | made again, the old one orphan | **renamed** (its `sha1` rewritten) when the text is kept, **made again** otherwise; the old one removed |
| reading position | **lost** | **moved** to the new sha1, its page **mapped** (cover: +1) |
| notes (future) | lost | moved, their pages mapped |
| journal of the reader events, "Mes lectures" | the history split, the old sessions dropped | see the aliases |
| URLs `/reader/<sha1>` (bookmarks, history of the browser), an open reader | 404; an open reader saves its position under the old sha1 | see the aliases |
| "ajouts récents" (sorted by mtime) | the book becomes the latest one | a date of addition in book.db (`added`, the mtime when the book was found first), used to sort instead of the mtime. Keeping the old mtime on the new file is not an option: a backup comparing size and mtime (rsync) could miss the change |
| original | lost | in the **Trash**: restorable; its disk space until the trash is emptied (an option of the command line to skip it) |
| server and command line | two processes writing book.db | the command line needs the server stopped (a lock file of the book directory, taken by both) |

## Aliases: the former sha1 of a book

An alias says "this sha1 is now this book". Three levels, from the
cheapest:

| | old URLs | history ("Mes lectures") | cost |
|---|---|---|---|
| A. none | 404 | split: the sessions before the replacement dropped | none |
| B. in the journal only: a line `{"t", "alias": old, "doc": new}` appended to `reader_events.jsonl` | 404 | whole: the reading of the journal maps `old` to `new` from this line on | a few lines in `srcs/history.py` and in the operation |
| C. in book.db: `former_sha1` of each book | redirect to the new sha1 (reader, PDF, book page, thumbnail), an open reader saves under the new sha1 | whole | an index in BookDir, one lookup used by the routes, schema v5, the life cycle below |

Life cycle of an alias (C; B has the same events in the journal):

1. **created** by a replacement: the old sha1 added to `former_sha1` of the
   book (a book optimized, then given a cover: two aliases);
2. **used** by the lookups by sha1 (`find_book_by_sha1()` falls back on the
   aliases: one place, every route benefits), by the reading of the
   journal, by the API of the reading positions;
3. **kept** while the book exists, missing books included (their entry is
   kept); a few dozen bytes each;
4. **dropped** when a file with this content is in the library again: the
   original restored from the Trash, or copied back. The scan finds a file
   whose sha1 is an alias: the alias is dropped, the file is a book of its
   own (the restore copies the user values to it, as a copy);
5. **gone** with the entry of the book, if it is ever removed from book.db.

Maintenance: the rule 4 in the scan, the fallback of the lookup, the
schema v5 (compatible: an older server ignores the field), their tests.
Recommendation: **B first** (the history kept for a small cost), C when
the old links matter (shared links, bookmarks of the browser).

## Steps

1. **Indicators** (no file changed): the measure of a PDF file (srcs), its
   cache `<sha1>.pdfstats.json` made with the metadata analysis, the
   `<details>` of the book page, `flask pdf audit` (the books worth an
   optimization first).
2. **`BookDir.transform()`**, the copy mode first: the cover page made
   with it (same behaviour as today), the checks of the new file.
3. **Replace mode**: original to the Trash, entry and caches following
   the new sha1, reading positions moved and mapped, `added` date for
   "ajouts récents", refusal with duplicates; the cover page offered "in
   place" or "as a copy" on the book page.
4. **Optimization** (per-page resources) as a transformation: the button
   of the book page, `flask pdf optimize` (server stopped, lock file).
5. **Aliases** (B, then C if wanted).

Set aside: the linearization (small gain once the resources are per
page), the recompression of the images (lossy).
