# -*- coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4

import os
import sys
import json
from flask import abort, current_app, jsonify, make_response, redirect, render_template, request, send_from_directory, session, url_for
from . import main
from ..book import BookDir
from ..cache import Cache

import io

@main.route('/')
def index():
    if request.path == '/' and 'username' in session:
        return redirect(url_for(".browser_lazy"))
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
        booklist = d.get_booklist()

    return render_template("browser.html",
                           titre = "eBook browser",
                           books = booklist,
                           categories = sorted(categories),
                           selected_category = selected_category,
                           )

SUBSET_NBBOOKS = 20

@main.route('/favicon.ico', methods=['GET'])
def favicon():
    return send_from_directory('static', 'favicon.ico', mimetype='image/vnd.microsoft.icon')

@main.route('/browser_lazy', methods=['GET'])
def browser_lazy():
    if not 'username' in session:
        return redirect(url_for(".login"))

    d = current_app.bookdir
    booklist = d.get_booklist()
    subset = booklist[:SUBSET_NBBOOKS]

    return render_template("browser_lazy.html",
                           titre = "eBook browser",
                           nbBooklist = len(booklist),
                           nbSubset = max(1, len(booklist) / SUBSET_NBBOOKS),
                           )

@main.route('/browser_subset', methods=['GET', 'POST'])
def browser_subset():
    if not 'username' in session:
        return redirect(url_for(".login"))

    d = current_app.bookdir
    booklist = d.get_booklist()
    nbBooks = len(booklist)

    subset_id = int(request.values.get('subset-id'))

    booklist = booklist[subset_id * SUBSET_NBBOOKS : subset_id * SUBSET_NBBOOKS + SUBSET_NBBOOKS]

    return render_template("bookbox.html", books = booklist)


@main.route('/browser_search', methods=['GET', 'POST'])
def browser_search():
    if not 'username' in session:
        return redirect(url_for(".login"))

    d = current_app.bookdir

    pattern = request.values.get('pat')
    print("pattern: " + pattern)

    s = d.get_subset_by_regexp(pattern)
    print("sublist size = " + str(len(s)))

    html = ""
    if len(s) < 200:

        html += render_template("bookbox.html", books = s)

    elif len(s) < 1000:

        html += '   <div>\n'

        for b in s:
                html += '    <p><a href="' + url_for('.pdf_read', pdffile = b.filename) + '">'
                html += b.get_name_and_size_as_str()
                html += "</a></p>\n"
        html += '   </div>\n'

    pluriel = 's' if len(s) > 1 else ''
    info_text = ' | La recherche a identifiée ' + str(len(s)) + ' livre' + pluriel

    # return a json
    j = {
        "body": html,
        "info-text": info_text,
    }

    return json.dumps(j)


dummyimg_resp = None

def dummyimg_get_response():

    global dummyimg_resp
    if not dummyimg_resp:
        from PIL import Image
        image = Image.new("RGB", (210,297), "#92C41D")
        with io.BytesIO() as output:
            image.save(output, 'BMP')
            dummyimg_resp = make_response(output.getvalue())
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
                            books = d.get_booklist(),
                            titre = "eBook admin")


@main.route("/pinbook", methods=['POST'])
def pinbook(sha1 = None):
    if not 'username' in session:
        return redirect(url_for("login"))

    # mandatory field
    if not request.form['id']:
        abort(400) # malformed

    d = current_app.bookdir

    sha1 = request.form['id']
    bsel = d.find_book_by_sha1(sha1)

    bsel.bookmarked = not bsel.bookmarked
    print("bsel.bookmarked = ", bsel.bookmarked)

    d.save_db()

    return jsonify({"pinned": bsel.bookmarked}), 200

#@main.errorhandler(401)
#@main.errorhandler(404)
#@main.errorhandler(500)
#def ma_page_erreur(error):
#    return "Ma jolie page {}".format(error.code), error.code
