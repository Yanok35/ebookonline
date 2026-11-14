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
from flask import Blueprint, abort, current_app, jsonify, make_response, redirect, render_template, request, send_file, send_from_directory, session, url_for
from app.auth import login_required
from srcs.book import BookDir
from srcs.cache import Cache

from werkzeug.security import check_password_hash, generate_password_hash


main = Blueprint('main', __name__)

_DUMMY_PWHASH = generate_password_hash("not-a-real-password")

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
        # Unknown users are checked against a dummy hash too, so that the
        # response time does not reveal which usernames exist.
        pwhash = creds.get(u, _DUMMY_PWHASH)
        if check_password_hash(pwhash, p) and u in creds:
            session['username'] = u
            current_app.logger.info("Login from %s: user %r", request.remote_addr, u)
            return redirect(url_for(".index"))

        # For fail2ban: the address first, the user name (chosen by the
        # client) can not be mistaken for it
        current_app.logger.warning("Login failed from %s: user %r", request.remote_addr, u)

        abort(401)
        return ("<h3>Error</h3>")

@main.route('/logout')
def logout():
    # remove the username from the session if it's there
    session.pop('username', None)
    return redirect(url_for('.index'))

@main.route('/browser', methods=['GET', 'POST'])
@login_required
def browser():
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
@login_required
def browser_lazy():
    d = current_app.bookdir
    booklist = d.get_booklist()
    subset = booklist[:SUBSET_NBBOOKS]

    return render_template("browser_lazy.html",
                           titre = "eBook browser",
                           nbBooklist = len(booklist),
                           nbSubset = max(1, len(booklist) // SUBSET_NBBOOKS),
                           )

@main.route('/browser_subset', methods=['GET', 'POST'])
@login_required
def browser_subset():
    d = current_app.bookdir

    s = d.get_booklist()
    sorted = request.values.get('sorted')
    if sorted:
        s = d.sort_by_date()
        current_app.logger.debug("Books sorted by date: %d", len(s))

    booklist = s
    nbBooks = len(booklist)

    subset_id = int(request.values.get('subset-id'))

    booklist = booklist[subset_id * SUBSET_NBBOOKS : subset_id * SUBSET_NBBOOKS + SUBSET_NBBOOKS]

    return render_template("bookbox.html", books = booklist)


@main.route('/browser_search', methods=['GET', 'POST'])
@login_required
def browser_search():
    d = current_app.bookdir

    pinned = request.values.get('pinned')
    if pinned:
        s = d.get_subset_if_bookmarked()
        current_app.logger.debug("Pinned books: %d", len(s))
    else:
        s = d.get_booklist()

    pattern = request.values.get('pat')
    if pattern:
        # typo tolerant, most relevant first
        s = d.search(pattern, s)
        current_app.logger.debug("Search %r: %d books", pattern, len(s))

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


# Shown until the thumbnail of a book is generated
MISSING_THUMBNAIL = "missing-thumbnail.png"

@main.route('/images/<sha1>')
@login_required
def image(sha1):
    #print(sha1)

    mon_image = current_app.cache.get_thumbnail(sha1)

    if mon_image:
        response = make_response(mon_image)
        response.mimetype = "image/jpeg"
    else:
        # Same URL: the browser revalidates it (ETag), and gets the
        # thumbnail once generated.
        response = send_from_directory(current_app.static_folder,
                                       MISSING_THUMBNAIL, mimetype="image/png")

    return response

def _present_book_or_404(sha1):
    """ The book of this sha1, if its PDF file is in the book directory """
    book = current_app.bookdir.find_book_by_sha1(sha1)
    if book is None or not book.present:
        abort(404)
    return book

@main.route('/pdf/<string:sha1>')
@login_required
def book_pdf(sha1):
    """ The PDF file of a book, from its sha1 (no file name in the URL) """
    book = _present_book_or_404(sha1)
    response = send_from_directory(
        current_app.bookdir.dirpath, book.filename,
        mimetype="application/pdf",
        # its name, when saved by the browser
        download_name=os.path.basename(book.filename),
        conditional=True,
    )
    # Allow Range HTTP request to get file by chunk (pdfjs uses chunks of 64KB)
    response.headers["Accept-Ranges"] = "bytes"
    return response

@main.route('/reader/<string:sha1>')
@login_required
def book_reader(sha1):
    """ The PDF reader (pdf.js) on a book, from its sha1 """
    book = _present_book_or_404(sha1)
    docName = os.path.basename(book.filename)
    return render_template("pdfjsviewer.html",
                            pdfurl = url_for('.book_pdf', sha1 = sha1),
                            documentId = sha1,
                            documentName = docName,
                            titre = docName)

@main.route('/readpdf/<path:pdffile>')
@login_required
def pdf_read(pdffile):
    # send_from_directory: a path out of the book directory is refused (404)
    response = send_from_directory(
        current_app.bookdir.dirpath, pdffile,
        conditional=True
    )
    # Allow Range HTTP request to get file by chunk (pdfjs uses chunks of 64KB)
    response.headers["Accept-Ranges"] = "bytes"
    return response

@main.route('/pdfjsviewer/<string:sha1>/<path:pdffile>')
@login_required
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

@main.route("/pinbook", methods=['POST'])
@login_required
def pinbook(sha1 = None):
    # mandatory field
    if not request.form['id']:
        abort(400) # malformed

    d = current_app.bookdir

    sha1 = request.form['id']
    bsel = d.find_book_by_sha1(sha1)

    bsel.bookmarked = not bsel.bookmarked
    current_app.logger.info("%s: %s '%s'", session.get("username"),
                            "pin" if bsel.bookmarked else "unpin", bsel.filename)

    d.save_db()

    return jsonify({"pinned": bsel.bookmarked}), 200

#@main.errorhandler(401)
#@main.errorhandler(404)
#@main.errorhandler(500)
#def ma_page_erreur(error):
#    return "Ma jolie page {}".format(error.code), error.code
