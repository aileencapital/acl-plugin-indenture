"""
Text-normalisation helpers and tunable config used by the extractors.

Ported verbatim from ACL_Indenture_cli.py (clean_text_for_matching,
is_cross_reference, NLP_CONFIG, SEARCH_CONFIG).
"""

from __future__ import annotations

import re


NLP_CONFIG = {
    "FUZZY_THRESHOLD": 85,
    "MIN_TERM_LENGTH": 2,
    "MAX_TERM_LENGTH": 60,
}

SEARCH_CONFIG = {
    "REQUIRE_QUOTES": True,
    "REQUIRE_COLON_OR_MEANS": True,
    "REQUIRE_CAPITALIZED": True,
    "DOC_TYPE": "CLO",
}


def clean_text_for_matching(text: str) -> str:
    return " ".join(text.split()) if text else ""


_CROSS_REF_PATTERNS = [
    r"shall\s+have\s+the\s+meaning\s+(?:given|ascribed|assigned)\s+to\s+such\s+term",
    r"is\s+defined\s+in\s+Section",
    r"has\s+the\s+meaning\s+set\s+forth\s+in",
    r"means\s+the\s+same\s+as",
]


def is_cross_reference(text: str) -> bool:
    for pattern in _CROSS_REF_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False
