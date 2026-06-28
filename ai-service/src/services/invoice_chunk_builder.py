"""Build retrieval chunks from the invoice profile so queries like
"what repair work / what was the total" can be answered from certified invoice docs."""

from __future__ import annotations

import logging

logger = logging.getLogger("invoice_chunk_builder")


def _fw_val(fw) -> str:
    if isinstance(fw, dict):
        v = fw.get("value")
        return str(v).strip() if v else ""
    return str(fw).strip() if fw else ""


def _build_vehicle_ctx(metadata: dict) -> str:
    parts = []
    veh = " ".join(p for p in [
        metadata.get("make"), metadata.get("model"), str(metadata.get("year") or "")
    ] if p).strip()
    if veh:
        parts.append(veh)
    if metadata.get("vin"):
        parts.append(f"VIN {metadata['vin']}")
    if metadata.get("chassisId"):
        parts.append(f"chassis {metadata['chassisId']}")
    if metadata.get("unit_number"):
        parts.append(f"unit {metadata['unit_number']}")
    return ", ".join(parts) if parts else "Vehicle"


def build_invoice_chunks(profile: dict, metadata: dict, document_id: str) -> list[dict]:
    """Return flat chunk dicts from the repair_invoice profile.

    Shape matches schema_chunk_builder output so prepare_chunks_for_upsert and
    build_parent_child_chunks work unchanged."""
    chunks: list[dict] = []
    vehicle_ctx = _build_vehicle_ctx(metadata)
    totals = profile.get("totals") or {}
    grand = _fw_val(totals.get("grand_total"))
    parts = _fw_val(totals.get("parts_total"))
    labor = _fw_val(totals.get("labor_total"))

    complaint = _fw_val(profile.get("complaint"))
    correction = _fw_val(profile.get("correction"))
    invoice_no = _fw_val(profile.get("invoice_no"))
    ro_no = _fw_val(profile.get("ro_no"))
    invoice_date = _fw_val(profile.get("invoice_date"))

    summary_parts = [f"{vehicle_ctx}."]
    if invoice_no:
        summary_parts.append(f"Invoice number: {invoice_no}.")
    if ro_no:
        summary_parts.append(f"Repair Order (RO): {ro_no}.")
    if invoice_date:
        summary_parts.append(f"Invoice date: {invoice_date}.")
    if complaint:
        summary_parts.append(f"Customer complaint: {complaint}.")
    if correction:
        summary_parts.append(f"Repair performed: {correction}.")
    if grand:
        summary_parts.append(f"Total invoice amount: ${grand}.")
    if parts:
        summary_parts.append(f"Parts total: ${parts}.")
    if labor:
        summary_parts.append(f"Labor total: ${labor}.")

    chunks.append({
        "pageNumber": 1,
        "sectionHeading": "Invoice summary",
        "chunkText": " ".join(summary_parts),
        "chunkType": "invoice_header",
        "coverageCodes": [],
    })

    items = profile.get("line_items") or []
    batch_size = 3
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        lines = [f"{vehicle_ctx}. Invoice line items:"]
        for item in batch:
            p = _fw_val(item.get("part_no"))
            d = _fw_val(item.get("description"))
            q = _fw_val(item.get("quantity"))
            ep = _fw_val(item.get("extended_price"))
            lines.append(f"  Part {p}: {d}, qty {q}, amount ${ep}.")
        chunks.append({
            "pageNumber": 1,
            "sectionHeading": f"Invoice line items {i + 1}-{i + len(batch)}",
            "chunkText": " ".join(lines),
            "chunkType": "invoice_line_items",
            "coverageCodes": [],
        })

    logger.info("invoice_chunk_builder: %d chunks (1 header + %d item batches)",
                len(chunks), len(chunks) - 1)
    return chunks
