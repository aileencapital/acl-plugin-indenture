"""
Tesseract OCR fallback for image-heavy PDF pages.

Ported from ACL_Indenture_cli.py:ocr_pdf_page. Returns "" on any error
so the caller can fall through to the next strategy without blowing up.
"""

from __future__ import annotations

import io
import logging

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None  # type: ignore

try:
    import pytesseract  # type: ignore
except ImportError:  # pragma: no cover
    pytesseract = None  # type: ignore

try:
    from PIL import Image  # type: ignore
except ImportError:  # pragma: no cover
    Image = None  # type: ignore

logger = logging.getLogger(__name__)


def ocr_pdf_page(pdf_path: str, page_number: int) -> str:
    if pytesseract is None or Image is None or fitz is None:
        return ""
    try:
        doc = fitz.open(pdf_path)
        page = doc.load_page(page_number - 1)
        pix = page.get_pixmap(dpi=300)
        pil_img = Image.open(io.BytesIO(pix.tobytes("png")))
        text = pytesseract.image_to_string(pil_img)
        doc.close()
        return text
    except Exception as e:
        logger.warning("OCR warning on page %s: %s", page_number, e)
        return ""
