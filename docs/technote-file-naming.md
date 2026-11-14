# Technical note: names of the PDF files after a pattern

The book page (`/bookadmin/<sha1>`) proposes a name for the PDF file of a
book, made from its metadata in `book.db` after a pattern, so that the files
of the library are named in the same way. Code: `srcs/naming.py`.

## Pattern

Setting `FILENAME_PATTERN`, by default:

```
{title} - {author_sort}, {year}
```

-> `Les Misérables - Hugo, Victor, 2012.pdf`.

| Variable | Value |
|----------|-------|
| `{title}` | Title |
| `{author}` | First author: `Victor Hugo` |
| `{authors}` | Authors: `A & B`, `A et al.` beyond 2 |
| `{author_sort}` | First author, surname first: `Hugo, Victor`, `Saint-Exupéry, Antoine de`, `van Beethoven, Ludwig`, `King, Martin Luther, Jr.` |
| `{editor}` | Editor (publisher) |
| `{year}` | Year |
| `{isbn}` | ISBN |

The pattern gives a file name only, without directory (the organization of
the directories is another step, see the TODO). It is checked at startup:
unknown variable, `/`, format specification (`{year:04}`) or no variable
refuse the start (`RuntimeError`).

## Name of a book

`naming.file_name(pattern, book)`:

- the values are the ones of `book.db`, entered or validated by the user,
  never the suggestions of the analysis;
- a missing value is left out, with its parentheses or brackets, its
  ` - ` separator or its comma: with the default pattern, no year gives
  `Les Misérables - Hugo, Victor.pdf`, no author `Les Misérables, 2012.pdf`,
  neither `Les Misérables.pdf`; with `{author_sort} - {title} ({year})`, no
  year gives `Hugo, Victor - Les Misérables.pdf`, no author
  `Les Misérables (2012).pdf`;
- no name when the pattern uses the title and the book has none, or when
  nothing is left;
- the values are cleaned up for any file system, Windows included (copies,
  Samba): `/` and `\` -> `-`, `:` -> ` -`, no `<>"|?*` nor control
  characters, single spaces, Unicode composed form (NFC), no dot or
  separator at the end;
- `.pdf` is appended; a name longer than 240 bytes (UTF-8) gets its title
  shortened at a word boundary.

## Book page

Under "Nouveau nom", in the file actions:

- "Selon le modèle : <name>", with a button "Utiliser" which sets it in the
  field: the name can still be changed before "Renommer";
- when another file of the directory has this name (e.g. another edition,
  with the same title, author and year), the first free name with a
  suffix, the convention of the trash: `name (2).pdf`, `name (3).pdf`,
  ... and the taken name is told; the file of the book itself does not
  count (`naming.free_name()`);
- "Nom conforme au modèle." when the file already has this name (or its
  name with a suffix, the name being taken);
- "Pas de nom selon le modèle : titre manquant." otherwise.

The name is made from the saved values: save the metadata first. The rename
is the usual one (`BookDir.rename_book()`): same directory, the
modification time of the file is kept; a name typed in the field which
exists is refused, as well as the proposed one when a file took it since
the page was shown (nothing is overwritten).
