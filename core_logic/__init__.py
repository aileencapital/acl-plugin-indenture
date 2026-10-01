"""
Pure-Python extraction primitives ported from ACL_Indenture_cli.py.

No Django imports anywhere in this package (authoring contract §2.6).
Re-exports the public surface that services.py orchestrates.
"""

from .text_processing import (
    clean_text_for_matching,
    is_cross_reference,
    NLP_CONFIG,
    SEARCH_CONFIG,
)
from .term_extractors import (
    find_defined_terms_nlp,
    find_defined_terms_fuzzy,
)
from .strategies import (
    auto_detect_clo_style,
    auto_detect_loan_style,
    auto_detect_isda_style,
    auto_detect_table_style,
    PATTERNS,
)
from .ocr import ocr_pdf_page
from .file_conversion import convert_docx_to_pdf, html_to_pdf

__all__ = [
    "clean_text_for_matching",
    "is_cross_reference",
    "NLP_CONFIG",
    "SEARCH_CONFIG",
    "find_defined_terms_nlp",
    "find_defined_terms_fuzzy",
    "auto_detect_clo_style",
    "auto_detect_loan_style",
    "auto_detect_isda_style",
    "auto_detect_table_style",
    "PATTERNS",
    "ocr_pdf_page",
    "convert_docx_to_pdf",
    "html_to_pdf",
]
