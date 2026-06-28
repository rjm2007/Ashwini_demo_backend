"""Parse warranty table rows into structured metadata for deterministic filtering."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

MONTHS_MILES_RE = re.compile(
    r"(\d+)\s*Months?\s*/\s*([\d,]+)\s*Miles?",
    re.IGNORECASE,
)
MONTHS_ONLY_RE = re.compile(r"(\d+)\s*Months?", re.IGNORECASE)
MILES_ONLY_RE = re.compile(r"([\d,]+)\s*Miles?", re.IGNORECASE)
UNLIMITED_MILES_RE = re.compile(r"unlimited\s*miles?", re.IGNORECASE)
DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
CODE_LEAD_RE = re.compile(
    r"^([A-Z]?\d{3,4}[A-Z]?|D\d{4}|ET\d{3}|TOW\d+)\b",
    re.IGNORECASE,
)


def _parse_int(value: str) -> int | None:
    try:
        return int(value.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _infer_categories(text: str) -> dict[str, bool]:
    t = text.lower()
    return {
        "engine_related": any(
            k in t
            for k in (
                "engine",
                "powertrain",
                "turbo",
                "epa",
                "emission",
                "ghg",
                "aftertreatment",
            )
        ),
        "transmission_related": any(
            k in t for k in ("transmission", "amt", "tow", "driveline", "drive shaft")
        ),
        "drivetrain_related": any(
            k in t
            for k in ("driveline", "drive", "axle", "differential", "transmission", "tow")
        ),
        "cab_related": any(k in t for k in ("cab", "hvac", "corrosion", "glass")),
    }


def parse_coverage_row(row_text: str, coverage_codes: list[str] | None = None) -> dict[str, Any]:
    """Extract structured fields from a single coverage table row or chunk."""
    text = (row_text or "").strip()
    meta: dict[str, Any] = {
        "duration_months": None,
        "mileage_limit": None,
        "unlimited_mileage": False,
        "start_date": None,
        "end_date": None,
        "warranty_type": None,
        "component_type": None,
        "coverage_category": None,
        "coverage_codes": list(coverage_codes or []),
    }
    if not text:
        return {**meta, **_infer_categories("")}

    mm = MONTHS_MILES_RE.search(text)
    if mm:
        meta["duration_months"] = _parse_int(mm.group(1))
        meta["mileage_limit"] = _parse_int(mm.group(2))
    else:
        mo = MONTHS_ONLY_RE.search(text)
        if mo:
            meta["duration_months"] = _parse_int(mo.group(1))
        mi = MILES_ONLY_RE.search(text)
        if mi:
            meta["mileage_limit"] = _parse_int(mi.group(1))

    if UNLIMITED_MILES_RE.search(text):
        meta["unlimited_mileage"] = True
        meta["mileage_limit"] = None

    dates = DATE_RE.findall(text)
    if len(dates) >= 1:
        meta["start_date"] = dates[0]
    if len(dates) >= 2:
        meta["end_date"] = dates[1]

    lead = CODE_LEAD_RE.match(text.replace("|", " ").strip())
    if lead and not meta["coverage_codes"]:
        meta["coverage_codes"] = [lead.group(1).upper()]

    cats = _infer_categories(text)
    meta.update(cats)

    if cats["engine_related"]:
        meta["coverage_category"] = "engine"
    elif cats["transmission_related"]:
        meta["coverage_category"] = "transmission"
    elif cats["drivetrain_related"]:
        meta["coverage_category"] = "drivetrain"
    elif cats["cab_related"]:
        meta["coverage_category"] = "cab"

    return meta


def parse_chunk_structured_meta(chunk: dict) -> dict[str, Any]:
    """Structured metadata for a chunk (row-level or legacy chunk)."""
    codes = chunk.get("coverageCodes") or []
    return parse_coverage_row(chunk.get("chunkText") or "", codes)
