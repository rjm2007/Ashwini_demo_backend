"""Build WARR-1172 summary response with stats rollup."""

from __future__ import annotations


def _period(row: dict) -> dict:
    return row.get("coverage_period") or {}


def build_summary_stats(schema: dict) -> dict:
    rows = schema.get("coverage_components") or []
    with_time = sum(1 for r in rows if _period(r).get("duration_months") is not None)
    with_mileage = sum(
        1
        for r in rows
        if _period(r).get("mileage_limit") is not None
        or _period(r).get("mileage_unit") == "unlimited"
    )
    with_lol = sum(1 for r in rows if r.get("limit_of_liability"))
    with_deductible = sum(1 for r in rows if r.get("deductible"))
    systems: set[str] = set()
    for row in rows:
        system = (row.get("coverage_hierarchy") or {}).get("system")
        if system:
            systems.add(str(system))
    return {
        "coverage_count": len(rows),
        "with_time_limit": with_time,
        "with_mileage_limit": with_mileage,
        "with_limit_of_liability": with_lol,
        "with_deductible": with_deductible,
        "system_count": len(systems),
        "extraction_confidence": (schema.get("document") or {}).get("extraction_confidence"),
    }


def build_summary_response(schema: dict, document_id: str, filename: str) -> dict:
    if not schema:
        return {
            "document": {},
            "warranty_program": {},
            "asset_context": {},
            "applicability": {},
            "coverage_components": [],
            "general_conditions": [],
            "general_exclusions": [],
            "stats": build_summary_stats({}),
            "document_id": document_id,
            "filename": filename,
        }
    return {
        **schema,
        "document_id": document_id,
        "filename": filename,
        "stats": build_summary_stats(schema),
    }
