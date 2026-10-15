import io

import fitz
from PIL import Image

from app.llm.client import _parse_angle, rotate_image
from app.parsing.pdf import render_pdf_pages


def test_parse_angle():
    assert _parse_angle("90") == 90
    assert _parse_angle("需要顺时针旋转180度") == 180
    assert _parse_angle("270") == 270
    assert _parse_angle("0") == 0
    assert _parse_angle("") == 0
    assert _parse_angle("不需要旋转") == 0


def _png(w=100, h=50):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_rotate_image_90_swaps_dimensions():
    out = rotate_image(_png(100, 50), 90)
    assert Image.open(io.BytesIO(out)).size == (50, 100)


def test_rotate_image_180_keeps_dimensions():
    out = rotate_image(_png(100, 50), 180)
    assert Image.open(io.BytesIO(out)).size == (100, 50)


def test_rotate_image_0_unchanged():
    png = _png(100, 50)
    assert rotate_image(png, 0) == png


def test_render_pdf_pages():
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    pdf_bytes = doc.tobytes()
    doc.close()
    pages = render_pdf_pages(pdf_bytes)
    assert len(pages) == 2
    for p in pages:
        img = Image.open(io.BytesIO(p))
        assert img.width > 0 and img.height > 0
