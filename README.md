# EBookOnLine

This project aim to provide a simple Http server based on Flask framework to
remotely access a local directory containing PDF files. The tool offers a very
basic login page and then an overview of all PDF as a set of clickable
thumbnails.

# Installation steps

## Clone this repository
```bash
git clone https://github.com/Yanok35/ebookonline.git
cd ebookonline/
```

## Create a virtual environment
```bash
python3 -m venv venv
source venv/bin/activate
```

## Install dependencies
```bash
sudo apt install zlib1g-dev libturbojpeg0-dev gcc libpython3.8-dev
CMAKE_BUILD_PARALLEL_LEVEL=4 pip3 install --extra-index-url https://www.piwheels.org/simple -r requirements.txt
```

## Policy tuning (ImageMagik 6 and later)
Please check security setting allows users to read pdf files, by following
entry in ```/etc/ImageMagick-6/policy.xml```

```
<policy domain="coder" rights="read" pattern="PDF" />
```


## Configure the service

`config.py` only holds non-sensitive defaults. Secrets are loaded at startup,
in this order (last one wins):

1. `config.py` (defaults, versioned),
2. `instance/config.py` (optional, **not versioned**), handy for development,
3. environment variables prefixed with `EBOOKONLINE_`, recommended in
   production. Values are parsed as JSON when possible;
   `EBOOKONLINE_A__B` sets the key `B` of the dictionary `A`.

Only the upper case names are settings; relative paths are relative to the
current directory. The server and the command line read them the same way
(`srcs/config.py`).

Two settings are required by the server (not by the command line):

- `SECRET_KEY`: used to sign session cookies, see the
  [Flask session documentation](https://flask.palletsprojects.com/en/stable/quickstart/#sessions).
- `CREDENTIALS`: a `{username: password hash}` dictionary.

Generate them with:

```bash
# secret key
python -c "import secrets; print(secrets.token_hex(32))"
# password hash (asked interactively)
python -c "import getpass; from werkzeug.security import generate_password_hash as h; print(h(getpass.getpass()))"
```

### Development: instance/config.py

```bash
cp instance/config.py.example instance/config.py
# then edit instance/config.py
```

### Production: environment variables

For instance in a systemd unit (or an `EnvironmentFile=` readable by root
only, as in `resources/ebookonline.service.sample`):

```ini
[Service]
Environment="EBOOKONLINE_SECRET_KEY=<generated key>"
Environment='EBOOKONLINE_CREDENTIALS={"yannick": "scrypt:32768:8:1$..."}'
```

### Paths

By default the server will search for PDF files in a subdirectory "books" as
referenced by the `BOOK_DIR` variable. Like any other setting it can be
overridden, e.g. `EBOOKONLINE_BOOK_DIR=/srv/books`.

The data written by the server, in the current directory by default:
`book.db` (`BOOK_DB`, the book list), `reader_events.jsonl`
(`READER_EVENTS_FILE`, the journal of the readings) and `userdata.db`
(`USERDATA_DB`, for each user: notes in the margin of the books, reading
positions, pins; see [technote-userdata.md](docs/technote-userdata.md)): to
back up, unlike `CACHE_DIR` (thumbnails, analyses: made again when
missing). `reader_states.json` (`STATE_FILE`) holds the reading positions
of before, common to all the users: read once, no longer written.

### Metadata analysis

The PDF files are analysed in background processes, at a low priority, to
suggest the title, subtitle, authors, editor, year and ISBN of the books in the admin
pages (nothing is written in `book.db` without the user). The results are
kept in `CACHE_DIR`, next to the thumbnails. See `METADATA_ANALYSIS`,
`METADATA_WORKERS` and `METADATA_NICE` in `config.py`, and
`docs/technote-metadata-extract-&-analysis.md`.

### Upload of books

A PDF or EPUB file dragged from the desktop and dropped on the library page
is uploaded to `BOOK_DIR/Incoming`. A PDF file is at once in the library;
an EPUB file is only stored there (the library has PDF files only). A file
whose name is already in `Incoming` is not sent (the page asks the server
first), and is never replaced. `UPLOAD_MAX_SIZE` (500 MB by default) is the
largest size. Not available in read-only mode.

### Theme of the reader

`READER_THEME`: `dark` (warm dark browns, the default) or `light` (the beige
look of the other pages), e.g. `EBOOKONLINE_READER_THEME=light`.

## Configure Apache as an Https proxy

TODO

The proxy must forward the request path percent-encoded, as sent by the
browser: gunicorn (27 and newer) rejects with a 400 error a path with raw
non-ASCII characters. The pages and the reader use the sha1 of the books
(`/reader/<sha1>`, `/pdf/<sha1>`), but the deprecated routes, kept for old
links, have the name of the PDF file in their path (`/readpdf/<file>`,
`/pdfjsviewer/<sha1>/<file>`), possibly with an accent. To check it through
the proxy (a redirection to the login page is expected, not 400):

```bash
curl -s -o /dev/null -w "%{http_code}\n" "https://<server>/readpdf/%C3%A9l%C3%A8ve.pdf"
```

## systemd service

`resources/ebookonline.service.sample` is an example of unit: gunicorn, run by
a dedicated user, only reachable from the reverse proxy, restarted on
failure, and only allowed to write in the project and book directories.
Adapt the user, the paths and the secrets file, then:

```bash
sudo install -m 644 -o root -g root resources/ebookonline.service.sample \
    /etc/systemd/system/ebookonline.service
sudo systemctl daemon-reload
sudo systemctl enable --now ebookonline
```

As for fail2ban, the unit is copied rather than linked (`systemctl link`):
it chooses the user and the command of the service.

# Operations

## Start the Flask production server

```bash
gunicorn -w 1 --threads 4 -b 127.0.0.1:5000 \
    --no-control-socket \
    --logger-class srcs.gunicorn_logger.GunicornLogger \
    'ebookonline:create_app()'
```

`-w 1`: a single process, which holds the book list in memory and writes
book.db; `--threads 4`: up to 4 requests served at once by this process.

`-b 127.0.0.1:5000`: only the reverse proxy, on the same host, can reach
the server. The application trusts the `X-Forwarded-For` header of the proxy
(`BEHIND_REVERSE_PROXY`): a client reaching gunicorn directly could choose
the address which is logged, thus banned by fail2ban.

`--no-control-socket`: no control socket for the `gunicornc` tool (gunicorn
25.1 and newer), which is not used. By default, gunicorn creates it in
`$XDG_RUNTIME_DIR`, unset for a system service, or else in the home
directory of the user, which a system user often does not have (e.g.
`Permission denied: '/nonexistent'` at startup).

`--logger-class` gives the messages of gunicorn itself the format of the
application (see [Logs](#logs)); their level is set by the gunicorn
`--log-level` option (`info` by default).

## Logs

Everything is logged on stderr, from the `LOG_LEVEL` setting (`INFO` by
default; e.g. `EBOOKONLINE_LOG_LEVEL=DEBUG`). Under systemd, journald
collects it, with the priority of each message:

```bash
journalctl -u ebookonline -f            # follow
journalctl -u ebookonline -p warning    # warnings and errors only
```

Outside of systemd (terminal), each line starts with the date and the level.

## Command line interface

`python -m srcs.cli`, run from the project directory with the Python of
the virtual environment, independent of the web server (Flask is not
loaded); `python -m srcs.cli help [COMMAND]` lists the commands. Commands
for the administrator, about the thumbnails:

- `thumbnails check [--list]`: counts the thumbnails by state (ok, missing,
  unreadable, cmyk) and lists the books whose thumbnail is not ok;
- `thumbnails regenerate`: regenerates the thumbnails selected by state
  (`--cmyk`, `--missing`, `--unreadable`, `--all`) or by book (sha1 or
  path), with `-n` to only list them, `--jobs N` processes, `--backend`
  to force a backend. A thumbnail is replaced once the new one is made,
  the old one is kept on failure.

and about the metadata analysis (see
[technote-metadata-extract-&-analysis.md](docs/technote-metadata-extract-&-analysis.md#command-line-srcsclipy)):

- `metadata scan`: analyses the PDF files not analysed yet (or outdated),
  with `-n`, `--jobs N`, `--force`; e.g. the initial analysis of a large
  library on a desktop computer, whose cache files are then copied to the
  server;
- `metadata show BOOK`: the values, suggestions and candidates of a book;
- `metadata stats`: state of the analysis, and agreement of the
  suggestions with the reviewed books, to tune the rules.

and about what makes a book slow to open in the reader (see
[technote-pdf-performance.md](docs/technote-pdf-performance.md)):

- `pdf audit`: measures the PDF files (kept in the cache directory), and
  lists them by the resources their heaviest page declares, with their
  warnings (`--warnings`: those with warnings only);
- `pdf show BOOK`: the indicators of a book (also in the book page,
  section "Structure du PDF").

`thumbnails help [COMMAND]`, `metadata help [COMMAND]` and
`pdf help [COMMAND]` show their options. They use the configuration of the
server (`SECRET_KEY` and `CREDENTIALS` not needed), start none of its
services, only read book.db, and can run while it runs. In production, as
the user of the service and with its settings (see
`resources/ebookonline.service.sample`):

```bash
sudo systemd-run --pty --wait --collect -p User=ebookonline -p Nice=10 \
    -p WorkingDirectory=/opt/ebookonline \
    -p EnvironmentFile=/etc/ebookonline/secrets.env \
    -E EBOOKONLINE_BOOK_DIR=/srv/books \
    /opt/ebookonline/venv/bin/python -m srcs.cli thumbnails check --list
```

Alternative command:

```bash
cd /opt/ebookonline
sudo -u nobody venv/bin/python -m srcs.cli thumbnails --help
```

## fail2ban configuration

The application logs, as warnings of its `app` logger:

- each failed login: `Login failed from <address>: user '<name>'`;
- each request of a page which does not exist (404) by a client which is not
  logged in, typically a scan for vulnerable software:
  `Not found from <address>: GET '<path>'`. A logged in user (e.g. a stale
  link) is only logged as info, with another message, and is never banned.

The address is the client given by the reverse proxy (see
`BEHIND_REVERSE_PROXY`), always before the user name or the path, which the
client chooses. fail2ban reads them from the journal.

Install the filter of `resources/fail2ban-filter.conf.sample` and the jails
of `resources/fail2ban-jail.local.sample` (one per kind of failure, with its
own threshold):

```bash
sudo install -m 644 -o root -g root resources/fail2ban-filter.conf.sample \
    /etc/fail2ban/filter.d/ebookonline.conf
sudo install -m 644 -o root -g root resources/fail2ban-jail.local.sample \
    /etc/fail2ban/jail.d/ebookonline.local
```

The files are copied, not linked: fail2ban runs as root, and a jail can run
any command as an action. A symbolic link to a file of the project would let
whoever can write in the project directory (e.g. the user of the server) run
commands as root. Copy them again after an update of the samples.

`journalmatch` (in the filter) must name the systemd unit of the server.
Check the filter on the journal, then the jails:

```bash
fail2ban-regex systemd-journal 'ebookonline[mode=auth]'
fail2ban-regex systemd-journal 'ebookonline[mode=notfound]'
fail2ban-client reload
fail2ban-client status ebookonline-notfound
```

# Development environement

## Source code

- `app/`: the web application (Flask): pages, API, admin pages.
- `srcs/`: the code without the web, used by `app/` and the command line:
  - `library/`: the book directory: its books (`book.py`), `book.db`
    (`bookdb.py`), the index and the scan (`bookdir.py`), the operations on
    its files (`operations.py`, `fileops.py`), the transformations of a book
    file (`transform.py`), the file names (`naming.py`), the search
    (`search.py`), the watcher (`watcher.py`);
  - `pdf/`: the PDF files themselves: thumbnails, indicators, cover page,
    transformations;
  - `metadata/`: the analysis of the metadata of the books;
  - `users/`: the data of each user (`userdata.db`), the journal of the
    readings;
  - `common/`: technical tools (files written atomically, versioned files,
    access checks, logs);
  - `config.py` (settings), `services.py`, `cli.py` (`python -m srcs.cli`),
    `gunicorn_logger.py`.

## Extend dependencies for dev

The project had initiated a use of `pytest` test framework, which can be installed using:

```bash
pip3 install -r requirements-dev.txt
```

And launch using:
```bash
pytest -s -v tests/
```

## Start the Flask server
```bash
FLASK_APP=ebookonline.py flask run --host=0.0.0.0 --reload --debug
./ebookonline.py runserver --host=0.0.0.0
```

# Licence

This project is shared under the GPL-3.0 licence terms and conditions.
Please refer to LICENCE file.
