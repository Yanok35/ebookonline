# -*- coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4

import os
import sys
from flask import abort, make_response, redirect, render_template, request, session, url_for
from . import main
from ..book import Book
from ..cache import Cache

from StringIO import StringIO

@main.route('/')
def index():
    if request.path == '/' and 'username' in session:
        return redirect(url_for(".browser"))
    else:
        return redirect(url_for(".login"))

@main.route('/login', methods=['GET', 'POST'])
def login():
    if 'username' in session:
        return redirect(url_for(".index"))

    if request.method == "GET":
        return render_template("login.html")
    else:
        u = request.form['username']
        p = request.form['password']

        #FIXME: quick&dirty stub to validate code migration...
        session['username'] = u
        return redirect(url_for(".index"))

        if u in creds.keys():
            if creds[u] == p:

                session['username'] = u

                return redirect(url_for(".index"))

        abort(401)
        return ("<h3>Error</h3>")

@main.route('/logout')
def logout():
    # remove the username from the session if it's there
    session.pop('username', None)
    return redirect(url_for('.index'))

@main.route('/browser')
def browser():
    if not 'username' in session:
        return redirect(url_for(".login"))

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
        Image.new("RGB", (210,297), "#92C41D").save(img, 'BMP')
        dummyimg_resp = make_response(img.getvalue())
        dummyimg_resp.mimetype = "image/bmp"

    return dummyimg_resp

@main.route('/images/<sha1>')
def image(sha1):
    #print(sha1)

    cache = Cache.get_instance()
    mon_image = cache.get_thumbnail(sha1)

    if mon_image:
        response = make_response(mon_image)
        response.mimetype = "image/jpeg"
    else:
        response = dummyimg_get_response()

    return response

@main.route('/readpdf/<path:pdffile>')
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

#@main.route("/bookadmin", methods=['GET', 'POST'])
#def admin():
#    if not 'username' in session:
#        return redirect(url_for("login"))
#
#    if request.method == "GET":
#        #Book.scan_dir(BOOK_DB, BOOK_DIR)
#        return render_template("bookadmin.html", titre = "eBook admin")
#    else:
#        s = request.form['username'] or None
#        pass #
#
#    response = make_response("<h1>Book admin for %s</h1>"
#            "<p>%s</p>" % (s, request.form))
#    return response
#
#@main.errorhandler(401)
#@main.errorhandler(404)
#@main.errorhandler(500)
#def ma_page_erreur(error):
#    return "Ma jolie page {}".format(error.code), error.code
