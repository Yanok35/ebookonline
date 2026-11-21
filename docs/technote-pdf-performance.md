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

## Optimization in place: consequences and mitigations

No copy in the cache (the disk space of production): an optimized book
replaces its file in `BOOK_DIR`. Its content changes, so does its sha1,
the identity of the book everywhere. What each place keyed by the sha1
becomes, today, and how to mitigate it:

| place | today (file changed in place, then rescan) | mitigation |
|---|---|---|
| book.db: user values (title, authors, tags, pinned, reviewed) | kept: the rescan sees "same path, new content", the entry takes the new sha1 | none needed; done by the operation itself rather than by the next rescan |
| book.db: the old sha1 | forgotten | **aliases**: book.db keeps `former_sha1` of the book (schema v5, compatible) |
| duplicates (other files with the old content) | broken: a copy keeps the old sha1, the entry of the book may follow the copy (seen as "moved"), the optimized file becomes a new book without user values | **refused** while the book has duplicates (or all its copies optimized together) |
| thumbnail `CACHE_DIR/<sha1>.jpg` | made again (the first page is the same); the old one stays, orphan | **renamed** to the new sha1 (same first page) |
| metadata analysis `<sha1>.meta.json.gz` | made again (a few seconds); the old one stays | **renamed**, its `sha1` field rewritten (same text) |
| reading position `reader_states.json` | **lost** (keyed by the old sha1) | **moved** to the new sha1 (same pages: the position stays valid) |
| journal of the reader events, timeline | the history is **split**; the old sessions are dropped from "Mes lectures" (unknown sha1) | journal kept as is (append only); the **aliases** are applied when it is read (`srcs/history.py`) |
| notes in the margin (future, by sha1) | lost | moved with the book (same pages: anchors valid) |
| links and bookmarks `/reader/<sha1>`, `/pdf/`, `/bookadmin/`, `/images/` | 404 | the **aliases** answer a redirect (301) to the new sha1 |
| an open reader tab | its positions saved under the old sha1 | the API maps an alias to the new sha1 |
| "ajouts récents" (sorted by mtime) | the book becomes the most recent one | the **mtime of the original kept** (os.utime) |
| original file | lost | moved to the **Trash** (restorable; disk ×2 until the trash is emptied; an option to skip it for a batch) |
| restore of the original from the Trash | a new book with the old sha1, which is an alias | restore: the alias is dropped, the restored file is a book of its own (its user values copied, as a copy with a cover page) |

### Safety of the optimized file

Before it replaces the original, the optimized file is checked: same
number of pages, same page sizes, same text of the pages (extracted), the
rendering of a few pages compared at low resolution (a small difference
only). Otherwise the optimization is refused and the original kept.

### The operation

`BookDir.optimize(sha1, steps)`, under the scan lock, as the file
operations of the book page:

1. measure the book (indicators); nothing to do: stop;
2. write the optimized file to a hidden temporary file next to it (ignored
   by the scan and the watcher), check it, compute its sha1;
3. move the original to the Trash, the optimized file to its path, with
   the mtime of the original;
4. the entry of the book: new sha1, size, mtime, `former_sha1` += old one;
5. rename the thumbnail and the metadata cache file, move the reading
   position (and the notes);
6. save book.db; the watcher then sees nothing to do (same mtime and size
   as in book.db).

### Book page and command line

- **Book page**: the indicators in a `<details>`, with the possible gain
  ("the first page needs 77.7 MB, 0.7 MB once optimized"), and a button
  "Optimiser" (with the steps chosen: per-page resources, linearization,
  images). The page then goes to the new URL (the old one redirects).
- **Command line** (`flask --app ebookonline pdf audit|optimize`): audit of
  the whole library (the books worth an optimization first), optimization
  by sha1 or path, or of all the books over a threshold, with `-n` (dry
  run). It writes book.db and `reader_states.json`: **the server must be
  stopped** (it keeps book.db in memory and would overwrite it); the
  command refuses to run while the server answers, or uses a lock file.

### Steps of the implementation

1. indicators: measure (srcs, a function of the PDF file), cache
   (`<sha1>.pdfstats.json`, with the metadata analysis), `<details>` of
   the book page, `flask pdf audit`;
2. aliases in book.db (v5), redirects of the old URLs, aliases applied to
   the history;
3. `BookDir.optimize()` with the per-page resources step, the checks, the
   moves of the sha1-keyed data; the button of the book page;
4. `flask pdf optimize` (server stopped);
5. later, the other steps (linearization with qpdf, images).

An alternative, larger: an identity of the book independent of its
content (an id in book.db), used by the URLs and the data instead of the
sha1. The sha1 would only detect moves and duplicates. Every URL and
store to migrate: the aliases give most of the benefit at a small cost.
