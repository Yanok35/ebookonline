# EBookOnLine

This project aim to provides a simple Http server based on Flask framework to
remotely access a local directory containing PDF Files. The tools offer a very
basic login page and then an overview of all PDF as a set of clickable
thumbnails.

Note that the authentication mechanism is completely unsecured, but it relied on
the use of an https server!

# Installation steps

## Create a virtual environment
```bash
virtualenv ebookonline
cd ebookonline
source bin/activate
```

## Install dependencies
```bash
sudo apt-get install libjpeg-dev
sudo apt-get install libmagickwand-dev
pip install flask
pip install Pillow
pip install PyPDF2
pip install wand
```

## Clone this repository
```bash
git clone https://github.com/Yanok35/ebookonline.git git
cd git/
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
# ./server.py
FLASK_APP=server.py flask run --host=0.0.0.0
```

