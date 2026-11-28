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

""" The files of the cache directory of a book: they follow it when its file is replaced """

import os

from srcs.common.files import remove_quietly


def move_caches(bookdir, old_sha1, new_sha1, path, keeps_first_page, keeps_text):
    """ The thumbnail and metadata analysis follow the book, or are made again """
    from srcs.pdf import stats as pdfstats
    from srcs.metadata import store

    cache_dir = bookdir.cache.cachedir
    thumbnail = bookdir.cache.get_thumbname(old_sha1)
    if keeps_first_page and os.path.exists(thumbnail):
        os.replace(thumbnail, bookdir.cache.get_thumbname(new_sha1))
    else:
        remove_quietly(thumbnail)
        bookdir.cache.create_thumbnail(path, new_sha1)
    entry = store.read(cache_dir, old_sha1)
    if keeps_text and entry is not None:
        entry["sha1"] = new_sha1
        store.write(cache_dir, entry)
    elif bookdir.metadata is not None:
        bookdir.metadata.request(new_sha1, path)
    remove_quietly(store.path(cache_dir, old_sha1))
    # the indicators: of the new file, measured when asked
    remove_quietly(pdfstats.path(cache_dir, old_sha1))
