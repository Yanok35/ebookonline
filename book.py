#!/usr/bin/env python
# -*- coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4

from cache import sha1_file
from flask import *

import os

#BOOK_DIR = os.path.abspath("books")

class Book:

    def __init__(self, sha1, filename, category):

        # object variables
        self.sha1 = sha1
        self.mtime = "toto"
        self.filename = filename
        self.category = category
        # TODO: self.filesize = 0
        
    
    def __str__(self):
        return (self.sha1 + '|' + self.filename)

    # class variables
    book_list = []

    @classmethod
    def find_book_by_sha1(cls, sha1):
        for b in cls.book_list:
            if b.sha1 == sha1:
                return b
        return None

    @classmethod
    def scan_dir(cls, book_dir):
        print("Scanning directory %s for PDF files..." % book_dir)
        for (dir, _, files) in os.walk(book_dir):

            #print('>>>', dir, files)

            # Book category is first level directory name
            category = dir.lstrip(book_dir)
            category = category.split('/')[0]
            if category == '':
                category = 'Generals'
            #print(category)

            for f in files:
                path = os.path.join(dir, f)
                if (path.lower().endswith("pdf")) and os.path.exists(path):
                    print("\t" + path)
                    k = sha1_file(path)

                    e = cls.find_book_by_sha1(k)
                    if e:
                        print("*** Warning: duplicate PDF files: %s\n"
                              "\t(%s already in cache)" % (path, e.filename))
                        continue

                    b = Book(k, path, category)
                    from cache import Cache
                    c = Cache.get_instance()
                    c.create_thumbnail(path, k)
                    cls.book_list.append(b)

    ##@classmethod
    ##def load_from_json(cls):
    ##    pass

    ##@classmethod
    ##def save_to_json(cls):
    ##    j = json.jsonify(cls.book_list)
    ##    print(j)
    ##    #j = json.jsonify({"a": 1, "b": "toto"})
    ##    #print(j.dumps)
    ##    pass

    @classmethod
    def get_html(cls):
        s = "<h1>Liste des livres</h1>"
        s += '<table border="1">'
        s += '<tr>'
        s += '<th>thumb</th>'
        s += '<th>filename</th>'
        s += '<th>sha1</th>'
        s += '</tr>'
        for b in cls.book_list:
            s += "<tr>"
            #s += '<td><img src="images/' + b.sha1 + '" width="300px"/></td>'
            s += '<td><img src="images/' + b.sha1 + '" width="150px"/></td>'
            s += "<td>" + b.filename + "</td>"
            s += "<td>" + b.sha1 + "</td>"
            s += "</tr>"
        s += '</table>'
        return s

