"""
DOCX → PDF conversion via headless LibreOffice.

Ported from ACL_Indenture_cli.py:convert_docx_to_pdf. The CLI used
`libreoffice` on the PATH on Windows; on this EC2 host both
`libreoffice` and `soffice` resolve to the same binary.
"""

from __future__ import annotations

import logging
import os
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
