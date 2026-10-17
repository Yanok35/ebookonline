import os
import pytest
from pathlib import Path

from srcs.cache import sha1_file

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

