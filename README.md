# EBookOnLine

This project aim to provides a simple Http server based on Flask framework to
remotely access a local directory containing PDF Files. The tools offer a very
basic login page and then an overview of all PDF as a set of clickable
thumbnails.

Note that the authentication mechanism is completely unsecured, but it relied on
the use of an https server!

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

You should edit ```ebookonline.conf``` file and modify following variables. A
secret key is required for cookies encryption in the
[Flask session documentation](http://flask.pocoo.org/docs/0.11/quickstart/#sessions).
Also, you should configure the user/password list by filling up the "creds"
dictionnary.

By default the server will search for PDF files in a subdirectory "books" as
referenced by the BOOK_DIR variable. You can configure this one according to
your needs.

```python
# You should generate a new one before hosting, using 'os.urandom(24)'
SECRET_KEY = 'A0Zr98j/3yX R~XHH!jmN]LWX/,?RT'

creds = {
    'yannick':  'test',
}

BOOK_DIR = os.path.abspath("books")
CACHE_DIR = os.path.abspath("cache")
BOOK_DB = "book.db"
```

## Configure Apache as an Https proxy

TODO

## Start the Flask server
```bash
# ./ebookonline.py
FLASK_ENV=debug FLASK_APP=ebookonline.py flask run --host=0.0.0.0
./ebookonline.py runserver --host=0.0.0.0
```

