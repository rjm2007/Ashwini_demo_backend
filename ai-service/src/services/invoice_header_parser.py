"""Deterministic extraction of invoice HEADER fields from invoice page text.

Mixed docs (invoice page + VDA table) classify as coverage_code_table, so LLM
invoice extraction never runs. This parser reads header fields, complaint,
correction, and totals from OCR text blocks directly.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("invoice_header_parser")


def _fw(value: Any, status: str = "extracted", page: int = 1) -> dict:
    if value in (None, ""):
        return {"value": None, "status": "missing", "confidence": 0.0, "page": page, "evidence_quote": ""}
    return {"value": value, "status": status, "confidence": 0.9, "page": page, "evidence_quote": ""}


_PATTERNS = {
    "invoice_no": r"invoice\s*#?\s*:?\s*([A-Z0-9\-]{4,})",
    "ro_no": r"(?:repair\s*order|r/?o)\s*#?\s*:?\s*(\d{3,})",
    "invoice_date": r"date\s*(?:/\s*hour)?\s*:?\s*(\d{1,2}/\d{1,2}/\d{2,4})",
    "unit_number": r"unit\s*(?:number|no\.?|#)?\s*:?\s*([A-Za-z0-9\-]{1,12})",
    "vin": r"vin\s*:?\s*([A-HJ-NPR-Z0-9]{17})",
    "meter": r"meter\s*:?\s*([\d,]+)\s*(?:kilometer|km|mile)",
    "in_service_date": r"in[- ]?service\s*date\s*:?\s*(\d{1,2}/\d{1,2}/\d{2,4})",
}

_BILL_TO_RE = re.compile(r"bill\s*to\s*:?\s*([A-Za-z0-9][A-Za-z0-9 &.\-]{2,40})", re.IGNORECASE)
_MAKE_MODEL_RE = re.compile(r"make\s*/?\s*model\s*:?\s*([A-Za-z]+)\s+([A-Za-z0-9]+)", re.IGNORECASE)

_MONEY = r"\$?\s*\(?([\d,]+\.\d{2})\)?"
_TOTAL_PATTERNS = {
    "parts_total": r"total[^\S\n]*parts?[^\S\n]*:?[^\S\n]*" + _MONEY,
    "labor_total": r"total[^\S\n]*labou?r[^\S\n]*:?[^\S\n]*" + _MONEY,
    "core_charge": r"total[^\S\n]*core[^\S\n]*charge[^\S\n]*:?[^\S\n]*" + _MONEY,
    "tax_total": r"(?:hst|gst)[^\S\n]*:?[^\S\n]*" + _MONEY,
    "grand_total": r"total[^\S\n]*invoice[^\S\n]*:?[^\S\n]*" + _MONEY,
}

_STOP_LABELS = (
    r"correction|make\s*/?\s*model|make\b|meter\b|ecm\b|department|model\s*year|"
    r"supp\.?|part\b|description|total\s+parts|tech\s*:|task\s*:|detail\s*tax|gst|page\b"
)
_COMPLAINT_RE = re.compile(
    r"complaint\s*:?\s*(.+?)(?=\s*(?:" + _STOP_LABELS + r")\s*:?)",
    re.IGNORECASE | re.DOTALL,
)
_CORRECTION_RE = re.compile(
    r"correction\s*:?\s*(.+?)(?=\s*(?:supp\.?|part\b|description|total\s+parts|"
    r"tech\s*:|task\s*:|detail\s*tax|gst|page\b)|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _find(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    return _clean(match.group(1)) if match else ""


def parse_invoice_header(text: str, page: int = 1) -> dict:
    """Extract header fields, complaint, correction, totals from invoice page text."""
    if not text:
        return {}

    out: dict[str, Any] = {}

    for key, pat in _PATTERNS.items():
        val = _find(pat, text)
        if val:
            out[key] = _fw(val, page=page)

    bill_to = _BILL_TO_RE.search(text)
    if bill_to:
        out["customer"] = _fw(_clean(bill_to.group(1)), page=page)

    make_model = _MAKE_MODEL_RE.search(text)
    if make_model:
        out["make"] = _fw(make_model.group(1).strip().title(), page=page)
        out["model"] = _fw(make_model.group(2).strip(), page=page)

    complaint_match = _COMPLAINT_RE.search(text)
    if complaint_match:
        complaint = _clean(complaint_match.group(1))[:400]
        if complaint:
            out["complaint"] = _fw(complaint, page=page)

    correction_match = _CORRECTION_RE.search(text)
    if correction_match:
        correction = _clean(correction_match.group(1))[:800]
        if correction:
            out["correction"] = _fw(correction, page=page)

    totals: dict[str, Any] = {}
    for key, pat in _TOTAL_PATTERNS.items():
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            totals[key] = _fw(match.group(1).replace(",", ""), page=page)
    if totals:
        out["totals"] = totals

    logger.info(
        "invoice_header_parser: %d header fields, complaint=%s, correction=%s, totals=%s",
        len([k for k in out if k != "totals"]),
        bool(out.get("complaint")),
        bool(out.get("correction")),
        list(totals),
    )
    return out


def looks_like_invoice(text: str) -> bool:
    """Heuristic: does this text contain repair-invoice markers?"""
    if not text:
        return False
    lowered = text.lower()
    markers = [
        "repair order", "total invoice", "total parts", "total labor",
        "complaint", "correction", "unit number",
    ]
    return sum(1 for marker in markers if marker in lowered) >= 2


def merge_invoice_header(profile: dict, parsed: dict) -> dict:
    """Merge parsed header into repair_invoice profile without overwriting existing values."""
    if not parsed:
        return profile
    parsed_copy = dict(parsed)
    parsed_totals = parsed_copy.pop("totals", {}) if isinstance(parsed_copy.get("totals"), dict) else {}
    for key, val in parsed_copy.items():
        existing = profile.get(key)
        if not existing or (isinstance(existing, dict) and existing.get("status") == "missing"):
            profile[key] = val
    if parsed_totals:
        totals = profile.setdefault("totals", {})
        for key, val in parsed_totals.items():
            existing = totals.get(key)
            if not existing or (isinstance(existing, dict) and existing.get("status") == "missing"):
                totals[key] = val
    return profile
