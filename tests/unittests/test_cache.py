import os
import pytest
import time

from pathlib import Path

from srcs.common.files import sha1_file
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
from tests.conftest import FakeCache, make_pdf, write_jpeg

need_gs = pytest.mark.skipif(not __import__("shutil").which("gs"), reason="Ghostscript (gs) required")


@need_gs
def test_ghostscript_jpeg_with_any_file_name(tmp_path, monkeypatch):
    # a name which would run a command in a shell string, with a '%' (a
    # page number for gs) and a leading '-'
    monkeypatch.chdir(tmp_path)
    pdf = make_pdf(tmp_path / '-a "$(touch pwned)" `touch pwned2` 100%.pdf')
    thumbname = "-100% thumb.jpg"
    assert FakeCache(tmp_path)._Cache__pdf2jpeg_ghostscript_jpeg(pdf.name, thumbname)
    assert (tmp_path / thumbname).read_bytes()[:2] == b"\xff\xd8"  # JPEG
    assert not (tmp_path / "pwned").exists() and not (tmp_path / "pwned2").exists()


@need_gs
def test_ghostscript_jpeg_failure(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a PDF file")
    thumbname = tmp_path / "bad.jpg"
    assert FakeCache(tmp_path)._Cache__pdf2jpeg_ghostscript_jpeg(str(bad), str(thumbname)) is False
    assert not thumbname.exists()


def test_ghostscript_jpeg_without_gs(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    pdf = make_pdf(tmp_path / "a.pdf")
    assert FakeCache(tmp_path)._Cache__pdf2jpeg_ghostscript_jpeg(str(pdf), str(tmp_path / "a.jpg")) is False


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


# --- choice of the backend ---

def backends_called(tmp_path, monkeypatch, backend, results):
    """ The backends run for a request, each one returning results[name] """
    cache = FakeCache(tmp_path)
    called = []
    for name, method in (("pypdf-wand", "resize_then_wand"), ("wand", "wand_only"),
                         ("ghostscript", "ghostscript_jpeg")):
        def run(pdffilename, thumbname, name=name):
            called.append(name)
            return results.get(name, False)
        monkeypatch.setattr(cache, f"_Cache__pdf2jpeg_{method}", run)
    monkeypatch.setattr(cache, "_Cache__thumb_resize_small", lambda thumbname: called.append("resize"))
    cache._thumbnail_job("a.pdf", str(tmp_path / "a.jpg"), backend)
    return called


def test_backends_in_turn(tmp_path, monkeypatch):
    assert backends_called(tmp_path, monkeypatch, None, {"wand": True}) == \
        ["pypdf-wand", "wand", "resize"]
    assert backends_called(tmp_path, monkeypatch, None, {}) == ["pypdf-wand", "wand", "ghostscript"]


def test_chosen_backend_only(tmp_path, monkeypatch, caplog):
    assert backends_called(tmp_path, monkeypatch, "ghostscript", {"ghostscript": True}) == \
        ["ghostscript", "resize"]
    # it fails: not the other ones
    with caplog.at_level(logging.ERROR):
        assert backends_called(tmp_path, monkeypatch, "wand", {"pypdf-wand": True}) == ["wand"]
    assert "No thumbnail for a.pdf (backend: wand)" in caplog.text


def test_create_thumbnail_unknown_backend(tmp_path):
    with pytest.raises(ValueError, match="unknown thumbnail backend"):
        FakeCache(tmp_path).create_thumbnail("a.pdf", "0" * 40, "magic")


def test_available_backends(monkeypatch):
    assert cache_module.available_backends()[:2] == ["pypdf-wand", "wand"]
    monkeypatch.setattr(cache_module.shutil, "which", lambda name: None)
    assert cache_module.available_backends() == ["pypdf-wand", "wand"]


def test_jpeg_size(tmp_path):
    write_jpeg(tmp_path / "a.jpg", 300, 424)
    assert cache_module.jpeg_size(tmp_path / "a.jpg") == (300, 424)
    # a progressive JPEG (SOF2), after an APP0 segment and fill bytes: the
    # header only
    sof2 = b"\xff\xc2\x00\x11\x08" + (5).to_bytes(2, "big") + (17).to_bytes(2, "big") + b"\x04"
    (tmp_path / "p.jpg").write_bytes(b"\xff\xd8\xff\xe0\x00\x04ab\xff\xff" + sof2)
    assert cache_module.jpeg_size(tmp_path / "p.jpg") == (17, 5)
    # the number of components: 4 for CMYK, 3 for RGB
    assert cache_module.jpeg_info(tmp_path / "p.jpg") == (17, 5, 4)
    assert cache_module.jpeg_info(tmp_path / "a.jpg") == (300, 424, 3)
    (tmp_path / "bad.jpg").write_bytes(b"\xff\xd8\xff")
    assert cache_module.jpeg_size(tmp_path / "bad.jpg") is None
    (tmp_path / "png.jpg").write_bytes(b"\x89PNG\r\n")
    assert cache_module.jpeg_size(tmp_path / "png.jpg") is None
    assert cache_module.jpeg_size(tmp_path / "missing.jpg") is None


# --- colours (CMYK) ---

def make_cmyk_pdf(path):
    """ A PDF file whose page is a CMYK image (a printed cover) """
    import pymupdf

    pix = pymupdf.Pixmap(pymupdf.csCMYK, pymupdf.IRect(0, 0, 60, 80), False)
    pix.set_rect(pix.irect, (200, 20, 80, 10))
    doc = pymupdf.open()
    page = doc.new_page(width=120, height=160)
    page.insert_image(page.rect, stream=pix.tobytes("jpg"))
    doc.save(path)
    return path


def centre_pixel(path):
    import pymupdf

    pix = pymupdf.Pixmap(str(path))
    return pix.pixel(pix.width // 2, pix.height // 2)


@need_gs
@pytest.mark.parametrize("backend", ["resize_then_wand", "wand_only"])
def test_wand_thumbnail_of_a_cmyk_pdf_is_rgb(tmp_path, backend):
    """
    In RGB, with the colours of Ghostscript: in CMYK, the browsers convert
    it naively (a teal becomes a fluorescent green)
    """
    pdf = make_cmyk_pdf(tmp_path / "cmyk.pdf")
    cache = FakeCache(tmp_path)
    if not getattr(cache, f"_Cache__pdf2jpeg_{backend}")(str(pdf), str(tmp_path / "w.jpg")):
        pytest.skip("ImageMagick refuses the PDF files (security policy)")
    assert cache_module.jpeg_info(tmp_path / "w.jpg")[2] == 3
    assert cache._Cache__pdf2jpeg_ghostscript_jpeg(str(pdf), str(tmp_path / "gs.jpg"))
    wand, gs = centre_pixel(tmp_path / "w.jpg"), centre_pixel(tmp_path / "gs.jpg")
    assert all(abs(a - b) <= 12 for a, b in zip(wand, gs)), (wand, gs)


def test_thumbnail_info_cmyk(tmp_path):
    cache = FakeCache(tmp_path)
    sha1 = "0" * 40
    sof = b"\xff\xc0\x00\x11\x08" + (450).to_bytes(2, "big") + (300).to_bytes(2, "big") + b"\x04"
    with open(cache.get_thumbname(sha1), "wb") as f:
        f.write(b"\xff\xd8" + sof)
    assert cache.thumbnail_info(sha1) == {"width": 300, "height": 450, "size": 12, "cmyk": True,
                                          "mtime": os.path.getmtime(cache.get_thumbname(sha1))}
    write_jpeg(Path(cache.get_thumbname(sha1)), 30, 40)
    assert cache.thumbnail_info(sha1)["cmyk"] is False


# --- thumbnail made now (command line) ---

def test_make_thumbnail_replaces_the_thumbnail(tmp_path, monkeypatch):
    cache = FakeCache(tmp_path)
    sha1 = "1" * 40
    thumbname = Path(cache.get_thumbname(sha1))
    thumbname.write_bytes(b"old")

    def ok(pdffilename, thumbname, backend):
        Path(thumbname).write_bytes(b"new")
        return True

    monkeypatch.setattr(cache, "_Cache__pdf2jpeg", ok)
    assert cache.make_thumbnail("a.pdf", sha1) is True
    assert thumbname.read_bytes() == b"new"

    def fail(pdffilename, thumbname, backend):
        Path(thumbname).write_bytes(b"partial")
        return False

    monkeypatch.setattr(cache, "_Cache__pdf2jpeg", fail)
    assert cache.make_thumbnail("a.pdf", sha1) is False
    # the previous thumbnail is kept, no temporary file left
    assert thumbname.read_bytes() == b"new"
    assert sorted(p.name for p in tmp_path.iterdir()) == [thumbname.name]


def test_cache_without_workers(tmp_path):
    cache = Cache(str(tmp_path / "cache"), workers=0)
    try:
        assert cache.subproc == []
    finally:
        cache.__del__()


def test_thumbnail_processes_replace_the_thumbnail_once_complete(tmp_path, monkeypatch):
    """ The image is made in a temporary file: the thumbnail never exists unfinished """
    cache = FakeCache(tmp_path)
    thumbname = Path(cache.get_thumbname("2" * 40))
    seen = []

    def make(pdffilename, tmpname, backend):
        Path(tmpname).write_bytes(b"big image, not resized yet")
        seen.append(thumbname.exists())
        Path(tmpname).write_bytes(b"resized")
        return True

    monkeypatch.setattr(cache, "_Cache__pdf2jpeg", make)
    assert cache._make_into("a.pdf", str(thumbname))
    assert seen == [False] and thumbname.read_bytes() == b"resized"
    assert sorted(p.name for p in tmp_path.iterdir()) == [thumbname.name]
