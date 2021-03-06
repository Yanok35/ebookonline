# -*- coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4

import os
import sys
from flask import abort, current_app, make_response, redirect, render_template, request, session, url_for
from . import main
from ..book import BookDir
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

        creds = current_app.config['CREDENTIALS']
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

@main.route('/browser', methods=['GET', 'POST'])
def browser():
    if not 'username' in session:
        return redirect(url_for(".login"))

    d = current_app.bookdir
    categories = d.get_list_of_category()

    selected_category = request.values.get('selected-category')

    if selected_category and selected_category != "all":
        booklist = d.get_subset_by_category(selected_category)
    else:
        booklist = d.booklist

    return render_template("browser.html",
                           titre = "eBook browser",
                           books = booklist,
                           categories = sorted(categories),
                           selected_category = selected_category,
                           )

SUBSET_NBBOOKS = 20

@main.route('/browser_lazy', methods=['GET'])
def browser_lazy():
    if not 'username' in session:
        return redirect(url_for(".login"))

    d = current_app.bookdir
    booklist = d.booklist[:SUBSET_NBBOOKS]

    return render_template("browser_lazy.html",
                           titre = "eBook browser",
                           books = booklist,
                           nbSubset = max(1, len(d.booklist) / SUBSET_NBBOOKS),
                           )

@main.route('/browser_subset', methods=['GET', 'POST'])
def browser_subset():
    if not 'username' in session:
        return redirect(url_for(".login"))

    d = current_app.bookdir
    booklist = d.booklist
    nbBooks = len(booklist)

    subset_id = int(request.values.get('subset-id'))

    booklist = booklist[subset_id * SUBSET_NBBOOKS : subset_id * SUBSET_NBBOOKS + SUBSET_NBBOOKS]

    html = ""
    for b in booklist:
        html += '   <div class="book-box">\n'
        html += '     <a href="' + url_for('.pdf_read', pdffile = b.filename) + '">\n'
        html += '     <div class="book-img">\n'
        html += '     <img src="' + url_for('.image', sha1 = b.sha1) + '" width="300px" />\n'
        html += '     </div>\n'
        html += '     </a>\n'
        html += '     <span class="caption simple-caption">\n'
        html += '     <p>' + b.get_name_and_size_as_str() + '</p>\n'
        html += '     <p>\n'
        html += '       <a href="' + url_for('.bookadmin', sha1 = b.sha1) + '">\n'
        html += '       <img src="/static/pencil.svg" width="20" height="20" />\n'
        html += '       </a>\n'
        html += '     </p>\n'
        html += '     </span>\n'
        html += '   </div>\n'


    return html


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
    #print(pdffile)
    #response = make_response(pdffile)
    #return response
    mon_pdf = StringIO()
    abspath = os.path.join(current_app.bookdir.dirpath, pdffile)
    n = open(abspath, 'rb')
    allin = n.read() #.decode('latin1')#.decode('iso8859-15')
    response = make_response(allin)
    response.mimetype = "application/pdf"
    return response

@main.route("/bookadmin/")
@main.route("/bookadmin/<sha1>", methods=['GET', 'POST'])
def bookadmin(sha1 = None):
    if not 'username' in session:
        return redirect(url_for("login"))

    d = current_app.bookdir

    bsel = None
    if sha1:
        bsel = d.find_book_by_sha1(sha1)

    edit_book_sha1 = request.values.get('book-sha1')

    if request.method == "POST":
        if 'tags' in request.form.keys():
            bsel.tags = request.form['tags']

        # Write json db
        d.save_db()
        return redirect(url_for(".bookadmin", sha1 = sha1))

    return render_template("bookadmin.html",
                            d = d,
                            bsel = bsel,
                            sha1 = sha1,
                            books = d.booklist,
                            titre = "eBook admin")

#@main.errorhandler(401)
#@main.errorhandler(404)
#@main.errorhandler(500)
#def ma_page_erreur(error):
#    return "Ma jolie page {}".format(error.code), error.code
