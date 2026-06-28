"""Build retrieval chunks from WARR-1172 coverage_components[]."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("warranty_chunk_builder")


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def build_vehicle_context(metadata: dict, schema: dict | None = None) -> str:
    schema = schema or {}
    asset = schema.get("asset_context") or {}
    applicability = schema.get("applicability") or {}
    make = _clean(metadata.get("make") or applicability.get("make") or asset.get("make"))
    model = _clean(metadata.get("model") or asset.get("model"))
    year = _clean(metadata.get("year"))
    vin = _clean(metadata.get("vin"))
    chassis = _clean(metadata.get("chassisId") or metadata.get("chassis_id") or asset.get("chassis_id"))

    parts: list[str] = []
    vehicle = " ".join(part for part in (make, model, year) if part).strip()
    if vehicle:
        parts.append(vehicle)
    if vin:
        parts.append(f"VIN {vin}")
    if chassis:
        parts.append(f"chassis {chassis}")
    return ", ".join(parts) if parts else "Vehicle identity unknown"


def _period_text(period: dict) -> str:
    period = period or {}
    bits = [_clean(period.get("duration_text"))]
    if period.get("duration_months") is not None:
        bits.append(f"{period['duration_months']} months")
    if period.get("mileage_limit") is not None:
        unit = period.get("mileage_unit") or "miles"
        bits.append(f"{period['mileage_limit']} {unit}")
    elif period.get("mileage_unit") == "unlimited":
        bits.append("unlimited mileage")
    return " / ".join(b for b in bits if b)


def build_warranty_chunks(master: dict, metadata: dict, document_id: str) -> list[dict]:
    """One Qdrant chunk per coverage_components[] row plus general sections."""
    vehicle_context = build_vehicle_context(metadata, master)
    chunks: list[dict] = []
    applicability = master.get("applicability") or {}
    asset = master.get("asset_context") or {}

    for row in master.get("coverage_components") or []:
        if not isinstance(row, dict):
            continue
        cid = _clean(row.get("coverage_id"))
        name = _clean(row.get("coverage_name"))
        if not cid:
            continue
        hierarchy = row.get("coverage_hierarchy") or {}
        period = row.get("coverage_period") or {}
        src = row.get("source_reference") or {}
        page = src.get("page") or 1

        text_parts = [
            f"{vehicle_context}.",
            f"Coverage {cid}: {name}.",
            f"Type: {_clean(row.get('coverage_type'))}.",
            f"Period: {_period_text(period)}.",
        ]
        for level in ("system", "subsystem", "component_group", "component"):
            val = hierarchy.get(level)
            if val:
                text_parts.append(f"{level}: {val}.")
        ref = _clean(src.get("text_reference"))
        if ref:
            text_parts.append(ref)

        payload_meta = {
            "coverage_id": cid,
            "coverage_type": row.get("coverage_type"),
            "system": hierarchy.get("system"),
            "subsystem": hierarchy.get("subsystem"),
            "component_group": hierarchy.get("component_group"),
            "make": metadata.get("make") or applicability.get("make") or asset.get("make"),
            "model": metadata.get("model") or (applicability.get("models") or [None])[0],
            "vin": metadata.get("vin") or asset.get("vin"),
            "asset_category": asset.get("asset_category") or applicability.get("asset_category"),
            "mileage_limit": period.get("mileage_limit"),
            "mileage_unit": period.get("mileage_unit"),
        }

        chunks.append(
            {
                "pageNumber": page,
                "sectionHeading": f"{cid} — {name[:60]}" if name else cid,
                "chunkText": " ".join(text_parts),
                "chunkType": "coverage_component",
                "coverageCodes": [cid],
                "structuredMeta": payload_meta,
            }
        )

    for section_type, items in (
        ("general_condition", master.get("general_conditions") or []),
        ("general_exclusion", master.get("general_exclusions") or []),
    ):
        for item in items:
            if not isinstance(item, dict):
                continue
            title = _clean(item.get("title")) or section_type.replace("_", " ").title()
            body = _clean(item.get("text"))
            if not body:
                continue
            chunks.append(
                {
                    "pageNumber": item.get("page") or 1,
                    "sectionHeading": title,
                    "chunkText": f"{vehicle_context}. {title}: {body}",
                    "chunkType": section_type,
                    "coverageCodes": [],
                }
            )

    logger.info(
        "warranty chunks: documentId=%s coverage_rows=%d total_chunks=%d",
        document_id,
        len(master.get("coverage_components") or []),
        len(chunks),
    )
    return chunks


def has_usable_warranty_schema(master: dict) -> bool:
    rows = master.get("coverage_components") if isinstance(master, dict) else None
    return isinstance(rows, list) and len(rows) >= 1


def extract_coverage_facts(master: dict) -> list[dict]:
    facts: list[dict] = []
    for row in master.get("coverage_components") or []:
        if not isinstance(row, dict):
            continue
        cid = _clean(row.get("coverage_id"))
        if not cid:
            continue
        period = row.get("coverage_period") or {}
        hierarchy = row.get("coverage_hierarchy") or {}
        facts.append(
            {
                "coverage_id": cid,
                "coverage_name": _clean(row.get("coverage_name")),
                "coverage_type": _clean(row.get("coverage_type")),
                "duration_months": period.get("duration_months"),
                "mileage_limit": period.get("mileage_limit"),
                "mileage_unit": period.get("mileage_unit"),
                "duration_text": _clean(period.get("duration_text")),
                "system": hierarchy.get("system"),
                "subsystem": hierarchy.get("subsystem"),
                "component_group": hierarchy.get("component_group"),
                "component": hierarchy.get("component"),
            }
        )
    return facts
