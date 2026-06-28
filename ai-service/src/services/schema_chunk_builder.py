"""Build deterministic retrieval chunks directly from extracted schema data."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("schema_chunk_builder")


def _fw(value: Any) -> Any:
    """Unwrap field-wrapper objects while treating missing values as empty."""
    if isinstance(value, dict) and "value" in value:
        if value.get("status") == "missing":
            return None
        return value.get("value")
    return value


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def build_vehicle_context(metadata: dict) -> str:
    """Return a compact vehicle identity string for retrieval context."""
    make = _clean(metadata.get("make"))
    model = _clean(metadata.get("model"))
    year = _clean(metadata.get("year"))
    vin = _clean(metadata.get("vin"))
    chassis = _clean(metadata.get("chassisId") or metadata.get("chassis_id"))

    parts: list[str] = []
    vehicle = " ".join(part for part in (make, model, year) if part).strip()
    if vehicle:
        parts.append(vehicle)
    if vin:
        parts.append(f"VIN {vin}")
    if chassis:
        parts.append(f"chassis {chassis}")
    return ", ".join(parts) if parts else "Vehicle identity unknown"


def _coverage_code_entries(master: dict) -> list[dict]:
    """Find coverage-code rows across the known schema nesting variants."""
    if not isinstance(master, dict):
        return []
    profiles = master.get("profiles") if isinstance(master.get("profiles"), dict) else {}
    candidates = [
        profiles.get("coverage_code_table", {}) if isinstance(profiles, dict) else {},
        profiles.get("coverage_codes_table", {}) if isinstance(profiles, dict) else {},
        master.get("coverage_code_table", {}),
        master,
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            codes = candidate.get("coverage_codes")
            if isinstance(codes, list) and codes:
                return codes
    return []


def build_schema_chunks(master: dict, metadata: dict, document_id: str) -> list[dict]:
    """Build one retrievable chunk per coverage code from master_schema_json."""
    vehicle_context = build_vehicle_context(metadata)
    chunks: list[dict] = [
        {
            "pageNumber": 1,
            "sectionHeading": "Vehicle identification",
            "chunkText": (
                f"Vehicle identification for this certified warranty document. "
                f"{vehicle_context}. This document lists warranty coverage codes, "
                "durations, mileage limits, and coverage periods for this vehicle."
            ),
            "chunkType": "vehicle_header",
            "coverageCodes": [],
        }
    ]

    entries = _coverage_code_entries(master)
    skipped = 0
    for entry in entries:
        if not isinstance(entry, dict):
            skipped += 1
            continue
        code = _clean(_fw(entry.get("code")))
        if not code:
            skipped += 1
            continue
        description = _clean(_fw(entry.get("description")))
        duration = _clean(_fw(entry.get("duration")))
        distance = _clean(_fw(entry.get("distance")))
        start_date = _clean(_fw(entry.get("start_date")))
        end_date = _clean(_fw(entry.get("end_date")))
        category = _clean(_fw(entry.get("category")))

        text_parts = [f"{vehicle_context}.", f"Coverage code {code}."]
        if description:
            text_parts.append(f"{description}.")
        if duration or distance:
            text_parts.append(f"Coverage limit: {' / '.join(p for p in (duration, distance) if p)}.")
        if start_date or end_date:
            text_parts.append(f"Coverage period: {start_date or 'unknown'} to {end_date or 'unknown'}.")
        if category:
            text_parts.append(f"Category: {category}.")

        chunks.append(
            {
                "pageNumber": _fw(entry.get("page")) or 1,
                "sectionHeading": f"{code} - {description[:60]}" if description else code,
                "chunkText": " ".join(text_parts),
                "chunkType": "coverage_code",
                "coverageCodes": [code],
                "structuredMeta": {
                    "coverage_codes": [code],
                    "duration_text": duration or None,
                    "distance_text": distance or None,
                    "start_date": start_date or None,
                    "end_date": end_date or None,
                    "category_label": category or None,
                },
            }
        )

    logger.info(
        "schema chunks: documentId=%s codes=%d chunks=%d skipped=%d",
        document_id,
        len(entries),
        len(chunks),
        skipped,
    )
    return chunks


def has_usable_schema(master: dict) -> bool:
    """Require at least two coverage codes before schema chunks replace fallback chunks."""
    return len(_coverage_code_entries(master)) >= 2


def extract_coverage_facts(master: dict) -> list[dict]:
    """Return compact, unwrapped coverage facts for prompt grounding."""
    facts: list[dict] = []
    for entry in _coverage_code_entries(master):
        if not isinstance(entry, dict):
            continue
        code = _clean(_fw(entry.get("code")))
        if not code:
            continue
        facts.append(
            {
                "code": code,
                "description": _clean(_fw(entry.get("description"))),
                "duration": _clean(_fw(entry.get("duration"))),
                "distance": _clean(_fw(entry.get("distance"))),
                "start_date": _clean(_fw(entry.get("start_date"))),
                "end_date": _clean(_fw(entry.get("end_date"))),
                "category": _clean(_fw(entry.get("category"))),
            }
        )
    return facts
