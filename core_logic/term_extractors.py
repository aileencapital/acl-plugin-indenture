"""
Term-extraction passes that work on plain text.

Ported from ACL_Indenture_cli.py: find_defined_terms_nlp (spaCy + fuzzy)
and find_defined_terms_fuzzy (strict regex).

The spaCy model is loaded once per process, lazily, and reused — the
original CLI loaded it inside the per-sentence loop, which is wasteful
on multi-page documents. The behavioural surface is unchanged.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from .text_processing import (
    NLP_CONFIG,
    SEARCH_CONFIG,
    clean_text_for_matching,
    is_cross_reference,
)

try:
    import spacy  # type: ignore
except ImportError:  # pragma: no cover
    spacy = None  # type: ignore

try:
    from rapidfuzz import fuzz  # type: ignore
except ImportError:  # pragma: no cover
    fuzz = None  # type: ignore

logger = logging.getLogger(__name__)


_NLP_MODEL = None


def _get_nlp():
    """Load en_core_web_sm once per process and reuse."""
    global _NLP_MODEL
    if _NLP_MODEL is None:
        if spacy is None:
            raise RuntimeError("spaCy is not installed")
        _NLP_MODEL = spacy.load("en_core_web_sm")
    return _NLP_MODEL


def find_defined_terms_fuzzy(
    text: str,
    terms: List[str],
    page_number: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    cleaned = clean_text_for_matching(text)
    for term in terms:
        q_open = r'[""“‘]' if SEARCH_CONFIG["REQUIRE_QUOTES"] else r""
        q_close = r'[""”’]' if SEARCH_CONFIG["REQUIRE_QUOTES"] else r""
        strict_pattern = f"{q_open}{re.escape(term)}{q_close}"

        for m in re.finditer(strict_pattern, cleaned, re.IGNORECASE):
            remaining = cleaned[m.end(): m.end() + 600]
            conn = (
                r"^\s*[:\-]?\s*(?:\bmeans\b|\bshall\s+mean\b)?\s*"
                if SEARCH_CONFIG["REQUIRE_COLON_OR_MEANS"]
                else r"^\s*"
            )
            def_match = re.search(
                f'{conn}([^"“‘]+)',
                remaining,
                re.IGNORECASE,
            )
            if def_match:
                definition = re.split(r"\.(?=\s)", def_match.group(1).strip())
                found.append({
                    "term": term,
                    "match": definition[0].strip(),
                    "page": page_number,
                    "confidence": 1.0,
                    "method": "Regex_Exact",
                })
    return found


def find_defined_terms_nlp(
    text: str,
    terms: List[str],
    page_number: Any,
) -> List[Dict[str, Any]]:
    if spacy is None or fuzz is None:
        logger.warning("NLP libraries missing — falling back to regex.")
        return find_defined_terms_fuzzy(text, terms, page_number)

    nlp_model = _get_nlp()
    doc = nlp_model(text)
    found: List[Dict[str, Any]] = []
    target_terms_lower = [t.lower() for t in terms]

    for sent in doc.sents:
        sent_text = sent.text.strip()
        if len(sent_text) < 20:
            continue
        if not re.search(
            r'\bmeans\b|\bshall\s+mean\b|\bis\s+defined\s+as\b|\bhas\s+the\s+meaning\b',
            sent_text,
            re.IGNORECASE,
        ):
            continue
        if is_cross_reference(sent_text):
            continue

        for noun_chunk in sent.noun_chunks:
            chunk_text = noun_chunk.text.strip()
            if (
                len(chunk_text) < NLP_CONFIG["MIN_TERM_LENGTH"]
                or len(chunk_text) > NLP_CONFIG["MAX_TERM_LENGTH"]
            ):
                continue

            for i, target in enumerate(target_terms_lower):
                clean_target = re.sub(r'[""“‘”’]', '', target)
                clean_chunk = re.sub(r'[""“‘”’]', '', chunk_text.lower())
                score = fuzz.token_sort_ratio(clean_target, clean_chunk)

                if score >= NLP_CONFIG["FUZZY_THRESHOLD"]:
                    term_pos = sent_text.lower().find(chunk_text.lower())
                    if term_pos != -1:
                        connector_match = re.search(
                            r'(?:means|shall\s+mean|is\s+defined\s+as|has\s+the\s+meaning)\s+',
                            sent_text[term_pos:],
                            re.IGNORECASE,
                        )
                        if connector_match:
                            definition_start = term_pos + connector_match.end()
                            definition = sent_text[definition_start:].strip()
                            if definition.endswith('.'):
                                definition = definition[:-1]
                            found.append({
                                "term": terms[i],
                                "match": definition[:600],
                                "page": page_number,
                                "confidence": round(score / 100, 2),
                                "method": "NLP_Fuzzy",
                            })
                            break
    return found
