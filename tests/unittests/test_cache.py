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

def _sleep_after_reset():
    import time

    from srcs.cache import _reset_signal_handlers
    _reset_signal_handlers()
    time.sleep(30)


def test_thumbnail_process_can_be_terminated():
    """
    A process forked from a gunicorn worker inherits its SIGTERM handler
    (graceful exit): reset, it is terminated at once by SIGTERM, as sent by
    multiprocessing to the daemon processes at exit.
    """
    import multiprocessing
    import signal

    previous = signal.signal(signal.SIGTERM, lambda signum, frame: None)
    try:
        p = multiprocessing.get_context("fork").Process(target=_sleep_after_reset, daemon=True)
        p.start()
        time.sleep(0.5)
        p.terminate()
        p.join(timeout=5)
        assert p.exitcode == -signal.SIGTERM
    finally:
        signal.signal(signal.SIGTERM, previous)


# --- Ghostscript fallback ---

from srcs import cache as cache_module
from tests.conftest import make_pdf

need_gs = pytest.mark.skipif(not __import__("shutil").which("gs"), reason="Ghostscript (gs) required")


@need_gs
def test_ghostscript_jpeg_with_any_file_name(tmp_path, monkeypatch):
    # a name which would run a command in a shell string, with a '%' (a
    # page number for gs) and a leading '-'
    monkeypatch.chdir(tmp_path)
    pdf = make_pdf(tmp_path / '-a "$(touch pwned)" `touch pwned2` 100%.pdf')
    thumbname = "-100% thumb.jpg"
    assert cache_module.ghostscript_jpeg(pdf.name, thumbname)
    assert (tmp_path / thumbname).read_bytes()[:2] == b"\xff\xd8"  # JPEG
    assert not (tmp_path / "pwned").exists() and not (tmp_path / "pwned2").exists()


@need_gs
def test_ghostscript_jpeg_failure(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a PDF file")
    thumbname = tmp_path / "bad.jpg"
    assert cache_module.ghostscript_jpeg(str(bad), str(thumbname)) is False
    assert not thumbname.exists()


def test_ghostscript_jpeg_without_gs(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    pdf = make_pdf(tmp_path / "a.pdf")
    assert cache_module.ghostscript_jpeg(str(pdf), str(tmp_path / "a.jpg")) is False


def test_failed_thumbnail_job_does_not_stop_the_process(tmp_path, monkeypatch, caplog):
    """ An error of a request is logged, and the incomplete thumbnail removed """
    from tests.conftest import FakeCache
    cache = FakeCache(tmp_path)
    thumbname = tmp_path / "a.jpg"

    def fail(pdffilename, thumbname):
        open(thumbname, "wb").close()
        raise OSError("resize failed")

    monkeypatch.setattr(cache, "_Cache__pdf2jpeg", fail)
    with caplog.at_level(logging.ERROR):
        cache._thumbnail_job("a.pdf", str(thumbname))
    assert "No thumbnail for a.pdf" in caplog.text
    assert not thumbname.exists()
