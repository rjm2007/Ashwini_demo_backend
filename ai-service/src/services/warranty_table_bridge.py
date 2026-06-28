"""Map Docling table rows (FIELD_WRAPPER) to WARR-1172 coverage_components[]."""

from __future__ import annotations

import logging
import re

from .coverage_table_parser import parse_coverage_codes_from_pipe_text, parse_coverage_codes_from_tables
from .warranty_normalizer import normalize_duration_period

logger = logging.getLogger("warranty_table_bridge")


def _fw_value(field: object) -> object:
    if isinstance(field, dict) and "value" in field:
        if field.get("status") == "missing":
            return None
        return field.get("value")
    return field


def _fw_page(field: object, default: int = 1) -> int:
    if isinstance(field, dict) and field.get("page"):
        return int(field["page"])
    return default


def _short_name(description: str, code: str) -> str:
    text = (description or "").strip()
    if not text:
        return code
    text = re.sub(rf"^{re.escape(code)}\s*[-:]?\s*", "", text, flags=re.I)
    text = re.split(r"\b\d+\s*(?:months?|mo|years?|days?)\b", text, maxsplit=1, flags=re.I)[0]
    text = text.strip(" -–—:")
    return text[:120] if text else code


def _build_period(duration: str, distance: str) -> dict:
    parts = [p for p in (duration, distance) if p]
    duration_text = " / ".join(parts) if parts else ""
    period = {
        "duration_text": duration_text or None,
        "duration_months": None,
        "mileage_limit": None,
        "mileage_unit": None,
        "hours_limit": None,
        "start_basis": None,
    }
    if distance and "unlimited" in distance.lower():
        period["mileage_unit"] = "unlimited"
    return normalize_duration_period(period)


def _merge_parsed_rows(*groups: list[dict]) -> list[dict]:
    """Union parser rows by coverage code; distinct codes are never collapsed."""
    by_code: dict[str, dict] = {}
    order: list[str] = []
    for group in groups:
        for entry in group:
            code = str(_fw_value(entry.get("code")) or "").upper()
            if not code:
                continue
            if code not in by_code:
                by_code[code] = entry
                order.append(code)
    return [by_code[c] for c in order]


def _apply_group_periods(parsed: list[dict]) -> list[dict]:
    """FIX F: propagate shared duration/distance from group headers to child rows."""
    group_duration = ""
    group_distance = ""
    out: list[dict] = []
    for entry in parsed:
        code = str(_fw_value(entry.get("code")) or "").strip()
        duration = str(_fw_value(entry.get("duration")) or "")
        distance = str(_fw_value(entry.get("distance")) or "")
        desc = str(_fw_value(entry.get("description")) or "")

        if not code and (duration or distance):
            group_duration = duration or group_duration
            group_distance = distance or group_distance
            continue

        if not code:
            continue

        if not duration and group_duration:
            entry = dict(entry)
            entry["duration"] = {"value": group_duration, "status": "extracted", "confidence": 0.9, "page": 1, "evidence_quote": ""}
        if not distance and group_distance:
            entry = dict(entry)
            entry["distance"] = {"value": group_distance, "status": "extracted", "confidence": 0.9, "page": 1, "evidence_quote": ""}

        out.append(entry)
    return out


def table_rows_to_coverage_components(
    structured_tables: list[dict] | None,
    tables_text: str = "",
) -> list[dict]:
    """Parse tables and return WARR-1172 coverage_components rows (raw; FIX A classifies)."""
    from_tables = parse_coverage_codes_from_tables(structured_tables or [])
    from_pipe = parse_coverage_codes_from_pipe_text(tables_text) if tables_text.strip() else []
    parsed = _apply_group_periods(_merge_parsed_rows(from_tables, from_pipe))

    rows: list[dict] = []
    for entry in parsed:
        code = str(_fw_value(entry.get("code")) or "").upper()
        if not code:
            continue
        description = str(_fw_value(entry.get("description")) or "")
        duration = str(_fw_value(entry.get("duration")) or "")
        distance = str(_fw_value(entry.get("distance")) or "")
        page = _fw_page(entry.get("code"), _fw_page(entry.get("description")))

        period = _build_period(duration, distance)
        name = _short_name(description, code)

        rows.append(
            {
                "coverage_id": code,
                "coverage_name_raw": description,
                "coverage_name": name,
                "coverage_hierarchy": None,
                "coverage_type": None,
                "coverage_period": period,
                "warranty_type": None,
                "source_reference": {
                    "page": page,
                    "text_reference": description[:500] if description else code,
                },
                "confidence_score": 0.95,
            }
        )

    logger.info("warranty_table_bridge: converted %d table rows", len(rows))
    return rows


def should_use_table_bridge(structured_tables: list[dict] | None, tables_text: str = "") -> bool:
    """Use deterministic bridge when enough coded rows are present."""
    from_tables = parse_coverage_codes_from_tables(structured_tables or [])
    from_pipe = parse_coverage_codes_from_pipe_text(tables_text) if tables_text.strip() else []
    return len(_merge_parsed_rows(from_tables, from_pipe)) >= 5
