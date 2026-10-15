from typing import List


def render_pdf_pages(pdf_bytes: bytes, dpi: int = 200) -> List[bytes]:
    """把 PDF 逐页渲染成 PNG 字节列表（扫描件按页转图，走视觉识别）。"""
    import fitz  # pymupdf

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pages: List[bytes] = []
    try:
        for page in doc:
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pages.append(pix.tobytes("png"))
    finally:
        doc.close()
    return pages
