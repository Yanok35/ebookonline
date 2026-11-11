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
pip3 install -r requirements.txt
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

## Start the Flask production server

```bash
gunicorn -w 1 -t 4 -b 0.0.0.0:5000 'ebookonline:create_app("default")'
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