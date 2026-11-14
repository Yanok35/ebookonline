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
CMAKE_BUILD_PARALLEL_LEVEL=4 pip3 install -r requirements.txt
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
   production. Values are parsed as JSON when possible.

Two settings are required:

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

For instance in a systemd unit (or an `EnvironmentFile=` readable by root only):

```ini
[Service]
Environment="EBOOKONLINE_SECRET_KEY=<generated key>"
Environment='EBOOKONLINE_CREDENTIALS={"yannick": "scrypt:32768:8:1$..."}'
```

### Paths

By default the server will search for PDF files in a subdirectory "books" as
referenced by the `BOOK_DIR` variable. Like any other setting it can be
overridden, e.g. `EBOOKONLINE_BOOK_DIR=/srv/books`.

## Configure Apache as an Https proxy

TODO

The proxy must forward the request path percent-encoded, as sent by the
browser: gunicorn (27 and newer) rejects with a 400 error a path with raw
non-ASCII characters, such as the name of a PDF file with an accent. To check
it through the proxy (a redirection to the login page is expected, not 400):

```bash
curl -s -o /dev/null -w "%{http_code}\n" "https://<server>/readpdf/%C3%A9l%C3%A8ve.pdf"
```

## Start the Flask production server

```bash
gunicorn -w 1 -t 4 -b 0.0.0.0:5000 \
    --logger-class srcs.gunicorn_logger.GunicornLogger \
    'ebookonline:create_app("default")'
```

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

## fail2ban

Each failed login is logged as `Login failed from <address>: user '<name>'`
(the client address given by the reverse proxy, see `BEHIND_REVERSE_PROXY`).

`/etc/fail2ban/filter.d/ebookonline.conf`:

```ini
[Definition]
failregex = ^.*?Login failed from <HOST>: user
journalmatch = _SYSTEMD_UNIT=ebookonline.service
```

`/etc/fail2ban/jail.d/ebookonline.conf`:

```ini
[ebookonline]
enabled = true
backend = systemd
filter = ebookonline
maxretry = 5
findtime = 10m
bantime = 1h
port = http,https
```

# Development environement

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
# ./ebookonline.py
FLASK_ENV=debug FLASK_APP=ebookonline.py flask run --host=0.0.0.0
./ebookonline.py runserver --host=0.0.0.0
```

# Licence

This project is shared under the GPL-3.0 licence terms and conditions.
Please refer to LICENCE file.