"""
Orchestration layer for the indenture extractor.

`run_extraction` wraps the CLI's `process_file_logic` flow but returns
structured Python data instead of writing CSV; `run_to_csv_bytes`
renders the CSV exactly as the CLI did (same columns, BOM, QUOTE_ALL,
sort order). The remaining helpers are thin wrappers over PluginData
for preset sets, run history, and user preferences.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from analytics_app.functions._framework.data_store import AppDataStore

from .core_logic import (
    auto_detect_clo_style,
    auto_detect_isda_style,
    auto_detect_loan_style,
    auto_detect_table_style,
    convert_docx_to_pdf,
    find_defined_terms_fuzzy,
    find_defined_terms_nlp,
    ocr_pdf_page,
)

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None  # type: ignore

try:
    import docx as _docx  # python-docx
except ImportError:  # pragma: no cover
    _docx = None  # type: ignore

logger = logging.getLogger(__name__)

APP_SLUG = "indenture"
MAX_HISTORY = 50
STRATEGIES = ["CLO", "CRA", "ISDA", "Table-Aware", "Smart"]
MODES = ["auto", "preset"]

DEFAULT_PREFS = {
    "default_strategy": "CLO",
    "default_mode": "auto",
    "default_preset_set_id": None,
}


# --- extraction pipeline ----------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _apply_strategy(
    strategy: str,
    text: str,
    location: Any,
    doc_path: Optional[str],
    page_num: Optional[int],
) -> List[Dict[str, Any]]:
    """Run the chosen auto-detect strategies against one page of text."""
    results: List[Dict[str, Any]] = []
    if strategy == "CLO":
        results.extend(auto_detect_clo_style(text, location))
    elif strategy == "CRA":
        results.extend(auto_detect_loan_style(text, location))
    elif strategy == "ISDA":
        results.extend(auto_detect_isda_style(text, location))
    elif strategy == "Smart":
        results.extend(auto_detect_clo_style(text, location))
        results.extend(auto_detect_loan_style(text, location))
        results.extend(auto_detect_isda_style(text, location))
    # Table-Aware adds the table strategy on top of nothing (PDF only).
    if strategy in ("Table-Aware", "Smart") and doc_path and page_num:
        results.extend(auto_detect_table_style(doc_path, page_num))
    return results


def _apply_preset(text: str, preset_terms: List[str], location: Any) -> List[Dict[str, Any]]:
    """NLP + regex preset matching with dedupe favouring the NLP pass."""
    nlp_results = find_defined_terms_nlp(text, preset_terms, location)
    regex_results = find_defined_terms_fuzzy(text, preset_terms, location)
    combined = list(nlp_results)
    seen = {r["term"].lower() for r in nlp_results}
    for r in regex_results:
        if r["term"].lower() not in seen:
            combined.append(r)
    return combined


def _dedupe(results: List[Dict[str, Any]], prefer_first: bool) -> List[Dict[str, Any]]:
    """Per-term dedupe matching the CLI's prefer_first / confidence rules."""
    unique: Dict[str, Dict[str, Any]] = {}
    for r in results:
        key = r["term"].lower()
        if key not in unique:
            unique[key] = r
            continue
        if prefer_first:
            continue
        existing = unique[key]
        r_conf = r.get("confidence", 0) or 0
        e_conf = existing.get("confidence", 0) or 0
        if r_conf > e_conf:
            unique[key] = r
        elif r_conf == e_conf and len(r.get("match", "")) > len(existing.get("match", "")):
            unique[key] = r
    return sorted(unique.values(), key=lambda x: x["term"])


def run_extraction(
    file_path: str,
    strategy: str,
    mode: str,
    preset_terms: Optional[List[str]],
    prefer_first: bool,
) -> Dict[str, Any]:
    """
    Runs the full extraction pipeline against one file. Returns a dict
    with ``pages_processed``, ``terms_found``, ``duration_ms``, and a
    ``results`` list of ``{term, page, definition, confidence, method}``
    rows. Raises ``FileNotFoundError`` if the file is missing,
    ``ValueError`` for an unsupported extension or invalid arguments,
    and ``RuntimeError`` if a required dependency is unavailable.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy!r}")
    if mode not in MODES:
        raise ValueError(f"Unknown mode: {mode!r}")
    if mode == "preset" and not preset_terms:
        raise ValueError("preset mode requires a non-empty preset list")

    started = time.monotonic()
    original_ext = os.path.splitext(file_path)[1].lower()
    if original_ext not in (".pdf", ".docx"):
        raise ValueError(f"Unsupported file format: {original_ext}")

    processing_path = file_path
    temp_pdf: Optional[str] = None
    raw_results: List[Dict[str, Any]] = []
    pages_processed = 0
    work_dir = os.path.dirname(file_path)

    try:
        if original_ext == ".docx":
            try:
                temp_pdf = convert_docx_to_pdf(file_path, work_dir)
                processing_path = temp_pdf
                current_ext = ".pdf"
            except Exception:
                logger.warning(
                    "DOCX→PDF conversion failed; falling back to paragraph extraction"
                )
                current_ext = ".docx"
        else:
            current_ext = ".pdf"

        if current_ext == ".pdf":
            if fitz is None:
                raise RuntimeError("PyMuPDF (fitz) is required for PDF extraction")
            with fitz.open(processing_path) as doc:
                total_pages = len(doc)
                pages_processed = total_pages
                for i in range(total_pages):
                    page_num = i + 1
                    page = doc.load_page(i)
                    text = page.get_text()
                    if len(text.strip()) < 15:
                        logger.debug("Page %s low text, running OCR", page_num)
                        text = ocr_pdf_page(processing_path, page_num)
                    location = f"Page {page_num}"
                    if mode == "preset":
                        raw_results.extend(_apply_preset(text, preset_terms or [], location))
                    else:
                        raw_results.extend(
                            _apply_strategy(strategy, text, location, processing_path, page_num)
                        )
        else:
            # DOCX paragraph fallback — only reached if LibreOffice conversion failed.
            if _docx is None:
                raise RuntimeError("python-docx is required for DOCX paragraph fallback")
            doc = _docx.Document(file_path)
            paragraphs = list(doc.paragraphs)
            pages_processed = len(paragraphs)
            for i, para in enumerate(paragraphs):
                if not para.text.strip():
                    continue
                location = f"Para {i + 1}"
                if mode == "preset":
                    raw_results.extend(_apply_preset(para.text, preset_terms or [], location))
                else:
                    raw_results.extend(
                        _apply_strategy(strategy, para.text, location, None, None)
                    )

        deduped = _dedupe(raw_results, prefer_first)

        normalised: List[Dict[str, Any]] = []
        for r in deduped:
            raw_loc = r.get("page", "0")
            page_num_only = re.sub(r"\D", "", str(raw_loc)) or "N/A"
            normalised.append({
                "term": r.get("term", ""),
                "page": page_num_only,
                "definition": r.get("match", ""),
                "confidence": r.get("confidence", "N/A"),
                "method": r.get("method", "Unknown"),
            })

        duration_ms = int((time.monotonic() - started) * 1000)
        return {
            "pages_processed": pages_processed,
            "terms_found": len(normalised),
            "duration_ms": duration_ms,
            "results": normalised,
        }
    finally:
        if temp_pdf and os.path.exists(temp_pdf):
            try:
                os.remove(temp_pdf)
            except OSError:
                pass


# --- CSV adapter ------------------------------------------------------------


def run_to_csv_bytes(run: Dict[str, Any]) -> bytes:
    """
    Render a stored run as CSV bytes matching the CLI output format
    exactly: UTF-8 with BOM, QUOTE_ALL, columns
    Term / Page / Definition / Confidence / Method.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL)
    writer.writerow(["Term", "Page", "Definition", "Confidence", "Method"])
    for row in run.get("results", []):
        writer.writerow([
            row.get("term", ""),
            row.get("page", "N/A"),
            row.get("definition", ""),
            row.get("confidence", "N/A"),
            row.get("method", "Unknown"),
        ])
    return buf.getvalue().encode("utf-8-sig")


# --- PluginData helpers -----------------------------------------------------


def _store(user) -> AppDataStore:
    return AppDataStore(app_slug=APP_SLUG, user=user)


# Run history

def save_run(user, run_data: Dict[str, Any]) -> str:
    """
    Persist a completed run under ``run:<uuid>`` and trim history to
    the most recent ``MAX_HISTORY`` entries. Returns the new run_id.
    """
    run_id = uuid.uuid4().hex
    store = _store(user)
    store.set(f"run:{run_id}", run_data)
    _trim_history(store)
    return run_id


def _trim_history(store: AppDataStore) -> None:
    keys = store.list_keys(prefix="run:")
    if len(keys) <= MAX_HISTORY:
        return
    runs = []
    for key in keys:
        value = store.get(key) or {}
        runs.append((value.get("processed_at", ""), key))
    runs.sort()  # oldest first
    for _, key in runs[: len(runs) - MAX_HISTORY]:
        store.delete(key)


def list_runs(user) -> List[Dict[str, Any]]:
    """Return all runs for the user, most recent first."""
    store = _store(user)
    out: List[Dict[str, Any]] = []
    for key in store.list_keys(prefix="run:"):
        value = store.get(key)
        if not isinstance(value, dict):
            continue
        out.append({
            "run_id": key.split(":", 1)[1],
            "filename": value.get("filename", ""),
            "strategy": value.get("strategy", ""),
            "mode": value.get("mode", ""),
            "preset_set_id": value.get("preset_set_id"),
            "pages_processed": value.get("pages_processed", 0),
            "terms_found": value.get("terms_found", 0),
            "processed_at": value.get("processed_at", ""),
            "duration_ms": value.get("duration_ms", 0),
        })
    out.sort(key=lambda r: r["processed_at"], reverse=True)
    return out


def get_run(user, run_id: str) -> Optional[Dict[str, Any]]:
    value = _store(user).get(f"run:{run_id}")
    return value if isinstance(value, dict) else None


# User preferences

def get_user_prefs(user) -> Dict[str, Any]:
    value = _store(user).get("user_prefs")
    if not isinstance(value, dict):
        return dict(DEFAULT_PREFS)
    merged = dict(DEFAULT_PREFS)
    merged.update(value)
    return merged


def save_user_prefs(
    user,
    strategy: str,
    mode: str,
    preset_set_id: Optional[str],
) -> None:
    _store(user).set("user_prefs", {
        "default_strategy": strategy,
        "default_mode": mode,
        "default_preset_set_id": preset_set_id,
    })


# Preset sets

def list_preset_sets(user) -> List[Dict[str, Any]]:
    store = _store(user)
    out: List[Dict[str, Any]] = []
    for key in store.list_keys(prefix="preset_set:"):
        value = store.get(key)
        if not isinstance(value, dict):
            continue
        out.append({
            "set_id": key.split(":", 1)[1],
            "name": value.get("name", ""),
            "terms": value.get("terms", []),
            "created_at": value.get("created_at", ""),
            "updated_at": value.get("updated_at", ""),
        })
    out.sort(key=lambda r: r["updated_at"], reverse=True)
    return out


def get_preset_set(user, set_id: str) -> Optional[Dict[str, Any]]:
    value = _store(user).get(f"preset_set:{set_id}")
    if not isinstance(value, dict):
        return None
    return {
        "set_id": set_id,
        "name": value.get("name", ""),
        "terms": value.get("terms", []),
        "created_at": value.get("created_at", ""),
        "updated_at": value.get("updated_at", ""),
    }


def save_preset_set(
    user,
    name: str,
    terms: List[str],
    set_id: Optional[str] = None,
) -> str:
    """Create or update a preset set; returns the set_id."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Preset set name is required")
    clean_terms = [t.strip() for t in terms if t and t.strip()]
    store = _store(user)
    now = _now_iso()
    if set_id:
        existing = store.get(f"preset_set:{set_id}") or {}
        created_at = existing.get("created_at", now)
    else:
        set_id = uuid.uuid4().hex
        created_at = now
    store.set(f"preset_set:{set_id}", {
        "name": name,
        "terms": clean_terms,
        "created_at": created_at,
        "updated_at": now,
    })
    return set_id


def delete_preset_set(user, set_id: str) -> None:
    _store(user).delete(f"preset_set:{set_id}")
