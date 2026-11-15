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


@pytest.mark.parametrize("valid", [True, False])
def test_pypdf_wand_thumbnail_leaves_no_temporary_file(tmp_path, monkeypatch, valid):
    """ The temporary PDF file of the first page is removed, success or not """
    import tempfile

    from tests.conftest import FakeCache

    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmpdir))
    if valid:
        pdf = make_pdf(tmp_path / "a.pdf")
    else:
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"not a PDF file")
    thumbname = tmp_path / "a.jpg"
    done = FakeCache(tmp_path)._Cache__pdf2jpeg_resize_then_wand(str(pdf), str(thumbname))
    assert list(tmpdir.iterdir()) == []
    if not valid:
        assert done is False
    elif done:  # (ImageMagick may refuse the PDF files: its security policy)
        assert thumbname.read_bytes()[:2] == b"\xff\xd8"


@pytest.mark.parametrize("name", ["k*.pdf", "m?.pdf", "a[1].pdf", "img:b.pdf", "@c.pdf", "d%d.pdf"])
def test_wand_thumbnail_with_any_file_name(tmp_path, monkeypatch, name):
    """
    The file is read whatever its name, and only it (glob characters: not
    another file); no temporary file is left
    """
    import tempfile

    from pypdf import PdfWriter
    from wand.image import Image

    from tests.conftest import FakeCache

    def pdf(path, width):
        writer = PdfWriter()
        writer.add_blank_page(width=width, height=297)
        with open(path, "wb") as f:
            writer.write(f)

    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmpdir))
    # relative names: a 'coder:' prefix would be interpreted
    monkeypatch.chdir(tmp_path)
    pdf(tmp_path / name, 100)
    for other in ("kz.pdf", "mz.pdf", "a1.pdf", "c.pdf"):
        pdf(tmp_path / other, 400)
    thumbname = tmp_path / "out.jpg"
    cache = FakeCache(tmp_path)
    if not cache._Cache__pdf2jpeg_wand_only("kz.pdf", str(thumbname)):
        pytest.skip("ImageMagick refuses the PDF files (security policy)")
    assert cache._Cache__pdf2jpeg_wand_only(name, str(thumbname))
    with Image(filename=str(thumbname)) as img:
        assert img.width < 200  # this file, not another one (400 points)
    assert list(tmpdir.iterdir()) == []
