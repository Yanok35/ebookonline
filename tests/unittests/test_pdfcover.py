import pymupdf
import pytest

from srcs.bookfileops import BookFileError
from srcs.pdfcover import (
    COVER_LABEL,
    MAX_IMAGE_PIXELS,
    check_image,
    image_info,
    insert_cover,
)


def image(fmt="jpeg", width=60, height=90):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), 0)
    pix.set_rect(pix.irect, (200, 60, 60))
    return pix.tobytes(fmt)


@pytest.fixture
def pdf(tmp_path):
    """ 3 pages (A4), with an outline, page labels, metadata and a link """
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page(width=595, height=842)
    doc.set_toc([[1, "Front", 1], [1, "Chapter", 2], [2, "Section", 3]])
    doc.set_page_labels([{"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1},
                         {"startpage": 1, "prefix": "", "style": "D", "firstpagenum": 1}])
    doc.set_metadata({"title": "A title", "author": "An author"})
    doc[1].insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(0, 0, 50, 50), "page": 2})
    path = tmp_path / "a.pdf"
    doc.save(path)
    return path


def test_image_info():
    assert image_info(image("jpeg", 60, 90)) == ("jpeg", 60, 90)
    assert image_info(image("png", 61, 91)) == ("png", 61, 91)


@pytest.mark.parametrize("data, message", [
    (b"GIF89a....", "not a JPEG or PNG image"),
    (b"", "not a JPEG or PNG image"),
    (b"\xff\xd8\xff\xe0\x00\x10JFIF", "invalid JPEG image"),
    (b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR" + b"\x00" * 8, "invalid PNG image size"),
    # header of a 100000 x 100000 PNG: not decoded
    (b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR" + (100000).to_bytes(4) * 2, "image too large"),
])
def test_invalid_image(data, message):
    with pytest.raises(BookFileError, match=message):
        image_info(data)


def test_max_pixels():
    # e.g. a photo of a cover
    assert MAX_IMAGE_PIXELS >= 5000 * 6000


@pytest.mark.parametrize("fmt", ["jpeg", "png"])
def test_damaged_image(fmt):
    data = image(fmt, 600, 900)
    assert check_image(data) == (fmt, 600, 900)
    # truncated: decoding fails, or MuPDF warns
    for cut in [60, len(data) // 2]:
        with pytest.raises(BookFileError, match=f"(invalid|damaged) {fmt.upper()} image"):
            check_image(data[:cut])


@pytest.mark.parametrize("fmt", ["jpeg", "png"])
def test_insert_cover(pdf, tmp_path, fmt):
    out = tmp_path / "out.pdf"
    insert_cover(pdf, image(fmt, 60, 90), out)

    doc = pymupdf.open(out)
    assert doc.page_count == 4
    # the width of the first page, the ratio of the image
    assert doc[0].rect == pymupdf.Rect(0, 0, 595, 595 * 90 / 60)
    assert len(doc[0].get_images()) == 1
    # outline, links and metadata follow the pages
    assert doc.get_toc() == [[1, "Front", 2], [1, "Chapter", 3], [2, "Section", 4]]
    assert [link["page"] for link in doc[2].get_links()] == [3]
    assert doc.metadata["title"] == "A title" and doc.metadata["author"] == "An author"
    # each page keeps its label
    assert [doc[i].get_label() for i in range(4)] == [COVER_LABEL, "i", "1", "2"]


def test_insert_cover_without_page_labels(tmp_path):
    doc = pymupdf.open()
    for _ in range(2):
        doc.new_page()
    doc.save(tmp_path / "a.pdf")
    insert_cover(tmp_path / "a.pdf", image(), tmp_path / "out.pdf")
    doc = pymupdf.open(tmp_path / "out.pdf")
    # the numbering of the pages is kept
    assert [doc[i].get_label() for i in range(3)] == [COVER_LABEL, "1", "2"]


def test_insert_cover_errors(pdf, tmp_path):
    out = tmp_path / "out.pdf"
    with pytest.raises(BookFileError, match="not a JPEG or PNG image"):
        insert_cover(pdf, b"not an image", out)
    (tmp_path / "bad.pdf").write_bytes(b"not a PDF file")
    with pytest.raises(BookFileError, match="can not read the PDF file"):
        insert_cover(tmp_path / "bad.pdf", image(), out)
    # a truncated image, with a valid header
    with pytest.raises(BookFileError, match="(invalid|damaged) PNG image"):
        insert_cover(pdf, image("png")[:60], out)
    assert not out.exists()


def test_insert_cover_in_encrypted_pdf(pdf, tmp_path):
    doc = pymupdf.open(pdf)
    doc.save(tmp_path / "locked.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256,
             user_pw="user", owner_pw="owner")
    with pytest.raises(BookFileError, match="password"):
        insert_cover(tmp_path / "locked.pdf", image(), tmp_path / "out.pdf")
