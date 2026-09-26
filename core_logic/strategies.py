"""
Strategy-specific term-detection passes.

Ported from ACL_Indenture_cli.py (PATTERNS, auto_detect_clo_style,
auto_detect_loan_style, auto_detect_isda_style, auto_detect_table_style).
pdfplumber is loaded lazily and the table strategy degrades to no-op
when it is unavailable, matching the original CLI's behaviour.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from .text_processing import clean_text_for_matching

try:
    import pdfplumber  # noqa: F401
except ImportError:  # pragma: no cover
    pdfplumber = None  # type: ignore

logger = logging.getLogger(__name__)


PATTERNS = {
    "CLO": re.compile(
        r'[""“‘]([^"”’‘]{2,60})[""”’]'
        r'\s*(?:[:\-]|(?:\bmeans\b|\bshall\s+mean\b))\s+'
        r'([^"“‘]+)',
        re.IGNORECASE,
    ),
    "LOAN": re.compile(
        r'\(?(?:each,?\s+a\s+)?[""“‘]([^"”’‘]{2,60})'
        r'[""”’]\)?\s*(?:[:\-]|(?:\bmeans\b|\bshall\s+mean\b))?\s+'
        r'([^.;]+)',
        re.IGNORECASE,
    ),
    "ISDA": re.compile(
        r'[""“‘]([^"”’‘]{2,60})[""”’]'
        r'\s+(?:means|has\s+the\s+meaning|shall\s+mean)\s+([^.;]+)',
        re.IGNORECASE,
    ),
}


def auto_detect_clo_style(text: str, page_number: Any) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    cleaned = clean_text_for_matching(text)
    for m in PATTERNS["CLO"].finditer(cleaned):
        term, definition = m.group(1).strip(), m.group(2).strip()
        # Trim multi-definition runs at the first ". <quote>" boundary so
        # the captured definition stops at the start of the next entry.
        split_def = re.split(r'\.(?=\s+[""“‘])', definition)
        found.append({
            "term": term,
            "match": split_def[0].strip() if split_def else definition,
            "page": page_number,
            "confidence": 1.0,
            "method": "Regex_Pattern",
        })
    return found


def auto_detect_loan_style(text: str, page_number: Any) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    cleaned = clean_text_for_matching(text)
    for m in PATTERNS["LOAN"].finditer(cleaned):
        found.append({
            "term": m.group(1).strip(),
            "match": m.group(2).strip(),
            "page": page_number,
            "confidence": 1.0,
            "method": "Regex_Pattern",
        })
    return found


def auto_detect_isda_style(text: str, page_number: Any) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    cleaned = clean_text_for_matching(text)
    for m in PATTERNS["ISDA"].finditer(cleaned):
        found.append({
            "term": m.group(1).strip(),
            "match": m.group(2).strip()[:500],
            "page": page_number,
            "confidence": 1.0,
            "method": "Regex_Pattern",
        })
    return found


def auto_detect_table_style(doc_path: str, page_number: int) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    if pdfplumber is None:
        return found
    try:
        with pdfplumber.open(doc_path) as pdf:
            if page_number > len(pdf.pages):
                return found
            page = pdf.pages[page_number - 1]
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if not row or not row[0]:
                        continue
                    cleaned_row = [
                        cell.strip().replace("\n", " ") if cell else ""
                        for cell in row
                    ]
                    term_idx = 0
                    while term_idx < len(cleaned_row) and not cleaned_row[term_idx]:
                        term_idx += 1
                    if term_idx >= len(cleaned_row):
                        continue
                    term = cleaned_row[term_idx]
                    def_idx = term_idx + 1
                    while def_idx < len(cleaned_row) and not cleaned_row[def_idx]:
                        def_idx += 1
                    if def_idx < len(cleaned_row):
                        definition = cleaned_row[def_idx]
                        if 2 < len(term) < 60:
                            found.append({
                                "term": term,
                                "match": definition[:600],
                                "page": f"Page {page_number} (Table)",
                                "confidence": 0.9,
                                "method": "Table",
                            })
    except Exception as e:
        logger.warning("Table extraction error on page %s: %s", page_number, e)
    return found
