import os
import pytest
import time

from pathlib import Path

from srcs.cache import sha1_file
from srcs.cache import Cache

directory = Path(os.path.dirname(__file__)) / ".." / "resources"
have_resources = True if any(directory.glob("*.pdf")) else False

import logging

@pytest.mark.skipif(not have_resources, reason = "Tests required some PDF in resources subdir")
def test_sha1():

    # Valid call and response
    fname = directory / "Brian Okken - Python Testing with pytest_ Simple, Rapid, Effective, and Scalable (2022, Pragmatic Bookshelf).pdf"
    assert os.path.exists(fname)
    assert sha1_file(fname) == "1a9d880fe7a73558032a29d2a522b4667810cf75"
    # logging.getLogger().debug(f"sha1 = {sha1_file(fname)}")

    # Valid exception raised
    fname = directory / "ThisFileIsNotThere.pdf"
    assert not os.path.exists(fname)
    with pytest.raises(Exception):
        sha1_file(fname)

def test_cache(tmp_bookdir):
    tmp_testdir, tst_bookdir, tst_cachedir = tmp_bookdir
    logging.getLogger().debug(f"{tmp_testdir}\n{tst_bookdir}\n{tst_cachedir}")

    # Note: at the end of context manager, the Cache.__exit__() is called and will free the rendering thread
    with Cache.get_instance(tst_cachedir) as cache:
        time.sleep(.2)
        logging.getLogger().debug(f"tst_cachedir = {tst_cachedir}")

    # Following also word, but requires explicit call to __del__() which is not what we want

# @pytest.mark.skip(reason = "No working")
# def test_cache_get_thumbname(tmp_bookdir):

    # tmp_testdir, tst_bookdir, tst_cachedir = tmp_bookdir

    with Cache.get_instance(tst_cachedir) as cache:
        time.sleep(1)
        sha1 = "1a9d880fe7a73558032a29d2a522b4667810cf75"
        name = cache.get_thumbname(sha1)
        assert name == str(tst_cachedir / str(sha1 + ".jpg"))