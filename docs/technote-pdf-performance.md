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

## Indicators

`srcs/pdf/stats.py` measures them with PyMuPDF, without rendering: one pass
over the objects of the file (weight by kind, images, fonts), then the
resources each page declares, measured once per resource dictionary
(pages sharing a dictionary, by reference or by a copy of its text, as
some books repeat a dictionary of hundreds of patterns in every page).
0.1 to 1.7 s per book (0.3 s for the book of 80.9 MB). Kept in
`CACHE_DIR/<sha1>.pdfstats.json` (version `STATS_VERSION`); the warnings
are computed when shown (`warnings()`), their thresholds can change.

- book page, section "Structure du PDF": measured when opened the first
  time (`/bookadmin/<sha1>/pdfstats`, an HTML fragment), then shown at
  once; the number of warnings in its title; "Mesurer à nouveau";
- command line: `python -m srcs.cli pdf audit` (the library, the
  heaviest first), `python -m srcs.cli pdf show BOOK`.

Warnings: a page declaring more than 10 MB of resources (shared when
with more than 20 images), CMYK or JPEG 2000 images, an image over 20
megapixels, Type 3 fonts, a content stream over 1 MB. Not warned: the
linearization and the incremental updates (small effects; the `%%EOF`
markers do not count the updates, a linearized file has two).

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

On the library of development (108 files), besides the book above: 1
book with shared resources (39 MB, every page declaring 719 images, 29
MB, through a dictionary of patterns repeated in each page), 14 with CMYK
images, 2 with very large images, 1 with Type 3 fonts.

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

Two transformations change the content of a book file in place: the
insertion of a cover page and the optimization of the resources. `srcs/pdf/transformations.py` describes each one: `apply(src,
dst)` writes the new file, `check(src, dst)` compares it with the
original (the number of pages, the size and the text of the first and
last pages, at `page_offset`), and what it keeps of the original: the
first page (`keeps_first_page`, then the thumbnail is kept), the text
(`keeps_text`, then the metadata analysis is kept), the move of the pages
(`page_offset`: +1 for a cover page).

### The optimization: resources per page

`ResourcesPerPage`: MuPDF rewrites the content stream of each page with
the resources it uses only (`page.clean_contents(sanitize=True)`), then
saves the file compacted (`garbage=3`, `deflate`). It keeps the first page
and the text (the thumbnail and the metadata analysis are renamed). Its
checks, besides the common ones: the text of every page, the rendering of
the first pages, the middle one and the last one compared at 30 %
(a byte of a pixel may differ by 16 at most, 0.5 % of them at most), and
a gain: refused when the heaviest page keeps more than half of its
resources ("nothing to gain"), so that a sha1 does not change for
nothing.

Book page: a button "Optimiser le PDF" in "Structure du PDF" when a page
declares more than 10 MB of resources; the message tells the resources of
the heaviest page before and after. On the book of 80.9 MB: 3.2 s, the
heaviest page from 74.3 MB to 1.7 MB, the first page of the reader at
20 Mbit/s from 11.1 s (21.9 MB downloaded) to 2.1 s (1.0 MB).

### `transform(bookdir, sha1, transformation)`, under the scan lock

In `srcs/library/transform.py`.

1. refused: a missing book, read-only mode, a book with copies in the
   library (duplicates), a transformed file which is a known book;
2. `apply()` into a hidden temporary file next to the original (ignored
   by the scan and the watcher), `check()`;
3. the new file gets the **modification time of the original** (a book
   of the library since then, not a new one in "ajouts récents");
4. the original goes to the trash, `Trash/<path> (original).pdf` (or
   `(original) (2).pdf`, ... after several transformations);
5. the new file takes its place: same path, same name;
6. the entry of the book: the new sha1 and size, the user values kept;
   the thumbnail and the metadata analysis renamed or made again, the
   indicators removed (measured again when asked);
7. book.db saved: the watcher then finds nothing to do.

The reading position belongs to the application: `app/api.py`
(`move_reader_state()`) moves it to the new sha1, its page moved by
`page_offset`, under the lock of the positions.

### `restore_original(bookdir, sha1)`: undo the last transformation

The latest `(original)` file of the book in the trash takes its place
again, the current file goes to the trash, `Trash/<path>
(transformed).pdf`. The entry takes the sha1 of the original back, the
position its page back (`page_offset` from the page counts). Button
"Restaurer l'original" of the book page, while an original is in the
trash.

### Consequences

| place | effect, mitigation |
|---|---|
| book.db | the same entry: path, user values; new sha1 and size |
| modification time | the one of the original (decided); the scan also compares the **size**: a file changed with the same modification time is hashed again (e.g. a crash between the replacement and the saving of book.db) |
| duplicates | refused while the book has copies in the library |
| thumbnail, metadata analysis | renamed when the first page / the text are kept, made again otherwise (cover page) |
| PDF indicators | of the new file, measured when asked |
| reading position | moved, its page moved by `page_offset` |
| history ("Mes lectures") | **no aliases** (decided): the sessions before the transformation are no longer shown for this book |
| old URLs (`/reader/<sha1>`, bookmarks) | 404 (decided); an open reader saves its position under the old sha1, orphan |
| original | in the trash until it is emptied: the disk space of the book twice meanwhile |
| restore of the `(original)` file by the trash page | a book of its own, next to the transformed one (use "Restaurer l'original" instead) |

### Steps

1. Indicators: done (`srcs/pdf/stats.py`, book page, `pdf audit|show`).
2. `transform()`, `restore_original()`, the cover page in place, the
   reading positions moved: done.
3. The optimization (resources per page): done.
4. Later: `python -m srcs.cli pdf optimize` (several books; the server stopped, as it
   keeps book.db in memory), the recompression of the images (lossy).

Set aside: the linearization (small gain once the resources are per
page), the aliases of the former sha1.
