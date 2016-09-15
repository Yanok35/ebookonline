#!/usr/bin/env python
# -*- coding:utf-8 -*-

import os
#from flask import Flask, redirect, request, make_response, render_template, url_for
#from flask import abort
from flask import *
from StringIO import StringIO

from cache import Cache
from book import Book

#
# Globals
#
is_user_connected = True #False

# user: password
creds = {
    'yannick':  'test',
}

BOOK_DIR = os.path.abspath("books")
CACHE_DIR = os.path.abspath("cache")
BOOK_DB = "book.db"

#
app = Flask(__name__)

#cache = Cache(CACHE_DIR)
cache = Cache.get_instance(CACHE_DIR)

import sys
print("set recursion limit from %d to 10000" % sys.getrecursionlimit())
sys.setrecursionlimit(10000)

@app.route('/')
def index():
    if request.path == '/' and is_user_connected:
        return redirect(url_for("browser"))
    else:
        return redirect(url_for("login"))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == "GET":
        return render_template("login.html")
    else:
        u = request.form['username']
        p = request.form['password']

        if u in creds.keys():
            if creds[u] == p:

                global is_user_connected
                is_user_connected = True

                return redirect(url_for("index"))

        abort(401)
        return ("<h3>Error</h3>")

@app.route('/browser')
def browser():
    if not is_user_connected:
        return redirect(url_for("login"))

    #Book.scan_dir(BOOK_DB, BOOK_DIR)

    return render_template("browser.html",
                           titre = "eBook browser",
                           books = Book.book_list,
                           )

dummyimg_resp = None

def dummyimg_get_response():

    global dummyimg_resp
    if not dummyimg_resp:
        from PIL import Image
        img = StringIO()
        Image.new("RGB", (150,300), "#92C41D").save(img, 'BMP')
        dummyimg_resp = make_response(img.getvalue())
        dummyimg_resp.mimetype = "image/bmp"

    return dummyimg_resp

@app.route('/images/<sha1>')
def image(sha1):
    #print(sha1)

    global cache
    mon_image = cache.get_thumbnail(sha1)

    if mon_image:
        response = make_response(mon_image)
        response.mimetype = "image/jpeg"
    else:
        response = dummyimg_get_response()

    return response

@app.route('/readpdf/<path:pdffile>')
def pdf_read(pdffile):
    pdffile = '/' + pdffile
    #print(pdffile)
    #response = make_response(pdffile)
    #return response
    mon_pdf = StringIO()
    n = open(pdffile, 'rb')
    allin = n.read() #.decode('latin1')#.decode('iso8859-15')
    response = make_response(allin)
    response.mimetype = "application/pdf"
    return response

@app.route("/bookadmin", methods=['GET', 'POST'])
def admin():
    if not is_user_connected:
        return redirect(url_for("login"))

    if request.method == "GET":
        #Book.scan_dir(BOOK_DB, BOOK_DIR)
        return render_template("bookadmin.html", titre = "eBook admin")
    else:
        s = request.form['username'] or None
        pass #

    response = make_response("<h1>Book admin for %s</h1>"
            "<p>%s</p>" % (s, request.form))
    return response

#@app.errorhandler(401)
#@app.errorhandler(404)
#@app.errorhandler(500)
#def ma_page_erreur(error):
#    return "Ma jolie page {}".format(error.code), error.code

if __name__ == '__main__':

    Book.scan_dir(BOOK_DB, BOOK_DIR)

    app.run(debug=True)
