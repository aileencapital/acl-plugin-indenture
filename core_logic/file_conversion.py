"""
DOCX → PDF conversion via headless LibreOffice; HTML and text → PDF with PyMuPDF.

Ported from ACL_Indenture_cli.py:convert_docx_to_pdf. The CLI used
`libreoffice` on the PATH on Windows; on this EC2 host both
`libreoffice` and `soffice` resolve to the same binary.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess

logger = logging.getLogger(__name__)


def convert_docx_to_pdf(input_path: str, output_dir: str) -> str:
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    output_pdf = os.path.join(output_dir, f"{base_name}_temp.pdf")
    logger.info("Converting DOCX to PDF: %s", os.path.basename(input_path))

    try:
        result = subprocess.run(
            [
                "libreoffice", "--headless", "--invisible",
                "--convert-to", "pdf",
                "--outdir", output_dir,
                input_path,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"LibreOffice failed: {result.stderr}")
        # LibreOffice writes <base>.pdf in the output dir — rename to the
        # _temp.pdf form so the caller can clean it up unambiguously.
        produced = os.path.join(output_dir, f"{base_name}.pdf")
        if os.path.exists(produced) and produced != output_pdf:
            shutil.move(produced, output_pdf)
        if not os.path.exists(output_pdf):
            alt_path = os.path.join(os.getcwd(), f"{base_name}.pdf")
            if os.path.exists(alt_path):
                shutil.move(alt_path, output_pdf)
            else:
                raise FileNotFoundError(f"Output not found at {output_pdf}")
        return output_pdf
    except Exception as e:
        logger.error("Conversion error: %s", e)
        raise


# ── HTML / text → PDF (SEC EDGAR exhibits, 1.1.0) ──

_EDGAR_TEXT = re.compile(r"<TEXT>(.*?)</TEXT>", re.S | re.I)


def html_to_pdf(input_path: str, output_dir: str) -> str:
    """Render an HTML or plain-text file to PDF with PyMuPDF's Story (no LibreOffice).

    EDGAR serves each document inside an SGML wrapper (<DOCUMENT><TYPE>...<TEXT>...</TEXT>):
    only the part inside <TEXT> is rendered. Scripts are ignored and nothing is fetched
    (missing images render as a placeholder). Returns the path of <base>_temp.pdf.
    """
    import html as html_lib

    import pymupdf

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    output_pdf = os.path.join(output_dir, f"{base_name}_temp.pdf")
    with open(input_path, "rb") as fh:
        text = fh.read().decode("utf-8", errors="replace")
    m = _EDGAR_TEXT.search(text)
    if m:
        text = m.group(1)
    if input_path.lower().endswith(".txt") or "<" not in text[:2000]:
        text = "<pre>" + html_lib.escape(text) + "</pre>"
    logger.info("Converting HTML/text to PDF: %s", os.path.basename(input_path))
    story = pymupdf.Story(html=text)
    writer = pymupdf.DocumentWriter(output_pdf)
    page = pymupdf.paper_rect("letter")
    where = page + (54, 54, -54, -54)
    more = 1
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()
    return output_pdf
