"""Deterministic normalization for WARR-1172 warranty schema."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any

_MONTHS_RE = re.compile(r"(\d+)\s*(month|months|mo)\b", re.IGNORECASE)
_YEARS_RE = re.compile(r"(\d+)\s*(year|years|yr)\b", re.IGNORECASE)
_DAYS_RE = re.compile(r"(\d+)\s*(day|days)\b", re.IGNORECASE)
_HOURS_RE = re.compile(r"([\d,]+)\s*(hour|hours|hrs?)\b", re.IGNORECASE)
_MILES_RE = re.compile(r"([\d,\.]+)\s*(k)?\s*(mile|miles|mi)\b", re.IGNORECASE)
_KM_RE = re.compile(r"([\d,\.]+)\s*(k)?\s*(km|kilometer|kilometers)\b", re.IGNORECASE)
_RANGE_YEARS_RE = re.compile(r"(\d+)\s*to\s*(\d+)\s*year", re.IGNORECASE)
_RANGE_MI_RE = re.compile(
    r"([\d,]+)\s*to\s*([\d,]+)\s*(?:mile|miles|mi|km|kilometer|kilometers)\b", re.IGNORECASE
)
_RANGE_MONTHS_RE = re.compile(r"(\d+)\s*/\s*(\d+)\s*(month|months|mo)\b", re.IGNORECASE)


def _slug(value: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip()).strip("-").upper()
    return s or "UNKNOWN"


def _num(s: str | None) -> int | None:
    s = (s or "").replace(",", "").strip()
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _miles(match: re.Match | None) -> int | None:
    if not match:
        return None
    base = _num(match.group(1))
    if base is None:
        return None
    if (match.group(2) or "").lower() == "k":
        base *= 1000
    return base


def normalize_duration_period(period: dict) -> dict:
    """Fill duration_months / mileage_limit / mileage_unit from duration_text."""
    period = dict(period or {})
    text = str(period.get("duration_text") or "")
    notes: list[str] = list(period.get("_notes") or [])

    p: dict[str, Any] = {
        "duration_text": text or None,
        "duration_months": period.get("duration_months"),
        "duration_days": period.get("duration_days"),
        "mileage_limit": period.get("mileage_limit"),
        "mileage_unit": period.get("mileage_unit"),
        "hours_limit": period.get("hours_limit"),
        "start_basis": period.get("start_basis"),
        "range": period.get("range"),
    }

    if p["duration_months"] is None:
        ry = _RANGE_YEARS_RE.search(text)
        if ry:
            lo, hi = int(ry.group(1)) * 12, int(ry.group(2)) * 12
            p["duration_months"] = hi
            p["range"] = {"duration_months_from": lo, "duration_months_to": hi}
        else:
            rm = _RANGE_MONTHS_RE.search(text)
            if rm:
                lo, hi = int(rm.group(1)), int(rm.group(2))
                p["duration_months"] = lo
                p["range"] = {"duration_months_from": lo, "duration_months_to": hi}
            elif _YEARS_RE.search(text):
                p["duration_months"] = int(_YEARS_RE.search(text).group(1)) * 12
            elif _MONTHS_RE.search(text):
                p["duration_months"] = int(_MONTHS_RE.search(text).group(1))
            elif _DAYS_RE.search(text):
                p["duration_days"] = int(_DAYS_RE.search(text).group(1))

    if re.search(r"unlimited", text, re.IGNORECASE):
        p["mileage_unit"] = "unlimited"
        p["mileage_limit"] = None
    elif p["mileage_limit"] is None:
        mi = _miles(_MILES_RE.search(text))
        km = _miles(_KM_RE.search(text))
        rm = _RANGE_MI_RE.search(text)
        if rm:
            lo, hi = _num(rm.group(1)), _num(rm.group(2))
            p["mileage_limit"] = hi
            p["mileage_unit"] = "miles" if "km" not in rm.group(0).lower() else "km"
            p["range"] = {**(p["range"] or {}), "mileage_from": lo, "mileage_to": hi}
        elif mi is not None:
            p["mileage_limit"] = mi
            p["mileage_unit"] = "miles"
        elif km is not None:
            p["mileage_limit"] = km
            p["mileage_unit"] = "km"

    h = _HOURS_RE.search(text)
    if h:
        p["hours_limit"] = _num(h.group(1))

    if p["mileage_limit"] is not None and p["mileage_limit"] <= 0:
        p["mileage_limit"] = None
        notes.append("mileage <=0 discarded (OCR damage)")
    if p["mileage_limit"] is not None and 0 < p["mileage_limit"] < 100:
        p["mileage_limit"] = None
        notes.append("mileage <100 discarded (likely OCR damage)")

    if notes:
        p["_notes"] = notes
    elif "_notes" in p:
        p.pop("_notes", None)

    return p


def normalize_coverage_row(row: dict) -> dict:
    out = dict(row)
    out["coverage_period"] = normalize_duration_period(out.get("coverage_period") or {})
    hierarchy = out.get("coverage_hierarchy") or {}
    if hierarchy:
        out["coverage_hierarchy"] = {
            "system": hierarchy.get("system"),
            "subsystem": hierarchy.get("subsystem"),
            "component_group": hierarchy.get("component_group"),
            "component": hierarchy.get("component"),
        }
    for opt in ("limit_of_liability", "deductible", "plan_tier"):
        if opt in out and out[opt] in (None, {}, ""):
            out.pop(opt, None)
    return out


def derive_document_id(schema: dict, filename: str = "") -> str:
    asset = schema.get("asset_context") or {}
    applicability = schema.get("applicability") or {}
    unit = asset.get("unit_number") or ""
    make = applicability.get("make") or asset.get("make") or "DOC"
    if unit:
        return f"WARR-{unit}-{_slug(make)[:12]}-001"
    seed = f"{filename}:{make}"
    h = hashlib.sha1(seed.encode()).hexdigest()[:6].upper()
    return f"WARR-{h}-{_slug(make)[:12]}-001"


def ensure_coverage_ids(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for i, row in enumerate(rows):
        r = dict(row)
        cid = (r.get("coverage_id") or "").strip()
        if not cid:
            h = r.get("coverage_hierarchy") or {}
            base = "-".join(
                _slug(x)
                for x in (
                    h.get("system"),
                    h.get("component_group") or h.get("component"),
                    r.get("coverage_name"),
                )
                if x
            )
            cid = f"{base or 'ROW'}-{i+1:02d}"
        while cid in seen:
            cid = f"{cid}-{i+1}"
        seen.add(cid)
        r["coverage_id"] = cid
        out.append(r)
    return out


def normalize_warranty_schema(
    schema: dict,
    *,
    filename: str = "",
    existing_vehicle: dict | None = None,
) -> dict:
    """Apply deterministic normalization and rollups."""
    out = dict(schema)
    existing_vehicle = existing_vehicle or {}

    applicability = dict(out.get("applicability") or {})
    asset = dict(out.get("asset_context") or {})
    for key in ("make", "model", "vin", "chassis_id", "unit_number"):
        if not asset.get(key) and existing_vehicle.get(key):
            asset[key] = existing_vehicle.get(key)
    if not applicability.get("make") and asset.get("make"):
        applicability["make"] = asset["make"]
    if not applicability.get("models") and asset.get("model"):
        applicability["models"] = [asset["model"]]
    out["asset_context"] = asset
    out["applicability"] = applicability

    rows = [normalize_coverage_row(r) for r in (out.get("coverage_components") or []) if isinstance(r, dict)]
    rows = ensure_coverage_ids(rows)
    out["coverage_components"] = rows

    scores = [float(r.get("confidence_score") or 0) for r in rows if r.get("confidence_score") is not None]
    doc = dict(out.get("document") or {})
    doc.setdefault("extraction_date", date.today().isoformat())
    doc["document_id"] = doc.get("document_id") or derive_document_id(out, filename)
    doc["extraction_confidence"] = round(sum(scores) / len(scores), 3) if scores else doc.get("extraction_confidence")
    if filename and not doc.get("source_file"):
        doc["source_file"] = filename
    out["document"] = doc

    out["rag_metadata"] = {
        "recommended_chunking": "one_chunk_per_coverage_component",
        "primary_filters": [
            "make", "model", "vin", "asset_category", "system", "subsystem",
            "component_group", "coverage_id", "coverage_type", "mileage_limit", "mileage_unit",
        ],
    }
    return out


def compute_required_fields_missing(schema: dict) -> bool:
    applicability = schema.get("applicability") or {}
    make = applicability.get("make")
    models = applicability.get("models") or []
    coverage = schema.get("coverage_components") or []
    if not make:
        return True
    if not models and not (schema.get("asset_context") or {}).get("model"):
        return True
    if len(coverage) == 0:
        return True
    return False


def compute_completeness(schema: dict) -> float:
    rows = schema.get("coverage_components") or []
    if not rows:
        return 0.0
    filled = sum(1 for r in rows if r.get("coverage_id") and r.get("coverage_name"))
    return round(filled / max(len(rows), 1), 3)
