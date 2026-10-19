# -*- coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4

# eBookOnline - A web portal to access your ebooks collection
# Copyright (C) 2021 Yannick Gicquel
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import os
import sys
import json
from flask import abort, current_app, jsonify, make_response, redirect, render_template, request, send_file, send_from_directory, session, url_for
from . import main
from srcs.book import BookDir
from srcs.cache import Cache

from datetime import datetime

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
                           nbSubset = max(1, len(booklist) // SUBSET_NBBOOKS),
                           )

@main.route('/browser_subset', methods=['GET', 'POST'])
def browser_subset():
    if not 'username' in session:
        return redirect(url_for(".login"))

    d = current_app.bookdir

    s = d.get_booklist()
    sorted = request.values.get('sorted')
    if sorted:
        print("sorted = " + str(sorted))
        s = d.sort_by_date()
        print("sublist(3) size = " + str(len(s)))

    booklist = s
    nbBooks = len(booklist)

    subset_id = int(request.values.get('subset-id'))

    booklist = booklist[subset_id * SUBSET_NBBOOKS : subset_id * SUBSET_NBBOOKS + SUBSET_NBBOOKS]

    return render_template("bookbox.html", books = booklist)


@main.route('/browser_search', methods=['GET', 'POST'])
def browser_search():
    if not 'username' in session:
        return redirect(url_for(".login"))

    d = current_app.bookdir

    s = []
    pinned = request.values.get('pinned')
    if pinned:
        print("pinned = " + str(pinned))
        s = d.get_subset_if_bookmarked()
        print("sublist(1) size = " + str(len(s)))

    pattern = request.values.get('pat')
    if pattern:
        print("pattern: " + pattern)
        s = d.get_subset_by_regexp(pattern, s)
        print("sublist(2) size = " + str(len(s)))

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

    mon_image = current_app.cache.get_thumbnail(sha1)

    if mon_image:
        response = make_response(mon_image)
        response.mimetype = "image/jpeg"
    else:
        response = dummyimg_get_response()

    return response

@main.route('/readpdf/<path:pdffile>')
def pdf_read(pdffile):
    abspath = os.path.join(current_app.bookdir.dirpath, pdffile)
    response = send_file(
        abspath,
        conditional=True
    )
    # Allow Range HTTP request to get file by chunk (pdfjs uses chunks of 64KB)
    response.headers["Accept-Ranges"] = "bytes"
    return response

@main.route('/pdfjsviewer/<string:sha1>/<path:pdffile>')
def pdfjs_read(sha1, pdffile):
    docId = sha1
    docName = os.path.basename(pdffile)
    # TODO: Check RFC-3986 & reserved char when present in 'pdffile' filename.
    #  https://metacpan.org/pod/URI::Escape
    return render_template("pdfjsviewer.html",
                            pdfurl = url_for('.pdf_read', pdffile = pdffile).replace("'", "%27"),
                            documentId = docId,
                            documentName = docName,
                            titre = docName)

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
                            mtimestr = datetime.fromtimestamp(bsel.mtime).strftime('%Y-%m-%d %H:%M:%S'),
                            titre = "eBook admin")

@main.route("/reset-thumbnail/<sha1>", methods=['POST'])
def reset_thumbnail(sha1):
    try:
        current_app.logger.warning(f"get_thumbname = {current_app.cache.get_thumbname(sha1)}")
        os.remove(current_app.cache.get_thumbname(sha1))
    except Exception:
        return make_response(f"Reset thumbnail {sha1} failed !")

    d = current_app.bookdir
    b = d.find_book_by_sha1(sha1)
    pdffile = os.path.join(b.book_dir, b.filename)
    current_app.logger.warning(f"filename= '{pdffile}'")
    current_app.cache.create_thumbnail(pdffile, sha1)
    return redirect(url_for(".bookadmin", sha1 = sha1))

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
