"""
schema_extraction_service.py — Per-section extraction pipeline.

Each classified section group gets its own focused LLM call.
Intermediate outputs are stored in documents.section_extracts_json.
Final merged output is documents.master_schema_json.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy import text

from ..config import settings
from ..database import SessionLocal
from ..services.llm_service import LlmService

logger = logging.getLogger("schema_extraction")

_PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _parse_json(raw: str) -> dict:
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return json.loads(s.strip())


def _fw_value(fw: object) -> Any:
    if isinstance(fw, dict):
        return fw.get("value")
    return None


def _clean_text(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"!\[[^\]]*\]\(data:image[^)]+\)", "", text, flags=re.IGNORECASE)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


# ─── Status normalization ─────────────────────────────────────────────────────

# Status synonyms the LLM may produce — normalized to canonical values.
_STATUS_EXTRACTED = {"extracted", "found", "present", "ok", "yes", "true"}
_STATUS_MISSING   = {"missing", "absent", "not_found", "none", "null", "n/a", ""}
_STATUS_LOW       = {"low_confidence", "low", "uncertain", "ambiguous"}


def _canonical_status(raw: object) -> str:
    """Map any LLM-produced status string to canonical extracted|missing|low_confidence."""
    if not isinstance(raw, str):
        return "missing"
    s = raw.strip().lower()
    if s in _STATUS_EXTRACTED:
        return "extracted"
    if s in _STATUS_LOW:
        return "low_confidence"
    if s in _STATUS_MISSING:
        return "missing"
    # Unknown values default to extracted if there's a value present, else missing
    return "extracted"


def _normalize_field_wrapper(fw: object) -> object:
    """
    Coerce a single field wrapper to canonical form:
      - status: extracted | missing | low_confidence
      - value: None when missing
      - missing keys filled with safe defaults
    """
    if not isinstance(fw, dict):
        return fw  # not a wrapper, leave alone
    if "value" not in fw and "status" not in fw:
        return fw  # plain dict, not a wrapper

    val = fw.get("value")
    has_value = val is not None and val != "" and val != []

    raw_status = fw.get("status")
    canonical = _canonical_status(raw_status)

    # Auto-correct: status says missing but value is present → extracted
    if canonical == "missing" and has_value:
        canonical = "extracted"
    # Auto-correct: status says extracted but value is empty → missing
    if canonical in ("extracted", "low_confidence") and not has_value:
        canonical = "missing"
        val = None

    return {
        "value": val,
        "status": canonical,
        "confidence": float(fw.get("confidence") or (0.0 if canonical == "missing" else 0.8)),
        "page": fw.get("page"),
        "evidence_quote": fw.get("evidence_quote"),
    }


def _normalize_field_wrappers_deep(obj):
    """Recursively normalize every field wrapper anywhere in the structure."""
    if isinstance(obj, dict):
        if "value" in obj and "status" in obj:
            return _normalize_field_wrapper(obj)
        return {k: _normalize_field_wrappers_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_field_wrappers_deep(item) for item in obj]
    return obj


def _count_extracted_in(obj) -> int:
    """Count how many field wrappers have status == 'extracted'."""
    n = 0
    def _walk(o):
        nonlocal n
        if isinstance(o, dict):
            if o.get("status") == "extracted" and o.get("value") not in (None, ""):
                n += 1
            else:
                for v in o.values(): _walk(v)
        elif isinstance(o, list):
            for x in o: _walk(x)
    _walk(obj)
    return n


# ─── Section groupings per document type ──────────────────────────────────────

# Maps (document_type, section_label) → which extraction module to call
# and what field schema to target. Each entry = one LLM call.
SECTION_EXTRACTION_MAP: dict[str, list[dict]] = {
    "warranty_certificate": [
        {
            "name": "vehicle_identification",
            "labels": ["vehicle_identification", "issuer_metadata"],
            "prompt_file": "extract_vehicle.txt",
            "fields": "make, model, model_year, vin, chassis_id, in_service_date, engine_family",
            "event_label": "Extracting: Vehicle & issuer details",
        },
        {
            "name": "coverage_summary",
            "labels": ["coverage_clause"],
            "prompt_file": "extract_coverage.txt",
            "fields": "base_duration, base_distance, major_duration, major_distance, coverage_basis, covered_components[]",
            "event_label": "Extracting: Coverage clauses",
        },
        {
            "name": "exclusions",
            "labels": ["exclusion", "legal_disclaimer"],
            "prompt_file": "extract_exclusions.txt",
            "fields": "exclusions[] (clause_no, title, text), towing (covered, cap_amount, conditions)",
            "event_label": "Extracting: Exclusions & limitations",
        },
        {
            "name": "claim_procedure",
            "labels": ["claim_procedure", "eligibility_condition"],
            "prompt_file": "extract_claim_procedure.txt",
            "fields": "claim_procedure, eligibility_conditions[], fuel_def_requirements",
            "event_label": "Extracting: Claim procedure & eligibility",
        },
    ],
    "coverage_code_table": [
        {
            "name": "vehicle_identification",
            "labels": ["vehicle_identification", "issuer_metadata"],
            "prompt_file": "extract_vehicle.txt",
            "fields": "make, model, model_year, vin, chassis_id, marketing_type, unit_number",
            "event_label": "Extracting: Vehicle identification",
        },
        {
            "name": "coverage_codes",
            "labels": ["coverage_code_row", "coverage_clause"],
            "prompt_file": "extract_coverage_codes.txt",
            "fields": "coverage_codes[] (code, description, category, duration, distance, start_date, end_date)",
            "event_label": "Extracting: Coverage codes table",
        },
    ],
    "repair_invoice": [
        {
            "name": "vehicle_and_header",
            "labels": ["vehicle_identification", "issuer_metadata"],
            "prompt_file": "extract_vehicle.txt",
            "fields": "make, model, model_year, vin, unit_number, meter_reading, in_service_date, invoice_no, ro_no, invoice_date, customer",
            "event_label": "Extracting: Vehicle & invoice header",
        },
        {
            "name": "line_items",
            "labels": ["invoice_line_item"],
            "prompt_file": "extract_invoice.txt",
            "fields": "complaint, correction, line_items[] (part_no, description, quantity, unit, unit_price, extended_price), totals (parts_total, labor_total, core_charge, tax_total, grand_total)",
            "event_label": "Extracting: Invoice line items & totals",
        },
    ],
    "generic_document": [
        {
            "name": "full_document",
            "labels": ["vehicle_identification", "coverage_clause", "issuer_metadata", "other"],
            "prompt_file": "extract_generic.txt",
            "fields": "document (title, issuer, date), vehicle (make, model, vin), extensions[]",
            "event_label": "Extracting: Document contents",
        }
    ],
}

def _collect_section_text(
    sections: list[dict],
    target_labels: list[str],
    md_content: str,
    plain_text: str,
    full_texts: list[dict] | None = None,
) -> str:
    """
    Returns extraction text for the requested classifier labels.

    - If sections matching target_labels are found:
        - For table-related labels → use md_content (Docling renders tables as md)
        - Otherwise → join the full text of matched sections (preview only as fallback)
    - If no labeled sections match → use full md_content (cleaned), then plain_text.
    """
    table_labels = {"coverage_code_row", "invoice_line_item"}
    use_md_table = bool(table_labels.intersection(target_labels))

    if use_md_table:
        return _clean_text(md_content or "")[: settings.schema_max_text_chars]

    matching = [s for s in sections if s.get("section_label") in target_labels]
    if matching:
        # Prefer full text from full_texts (if available) over previews
        if full_texts:
            idx_to_full = {t.get("index"): (t.get("text") or "") for t in full_texts}
            joined = "\n\n".join(
                idx_to_full.get(s.get("index")) or s.get("text_preview", "")
                for s in matching
            )
        else:
            joined = "\n\n".join(s.get("text_preview", "") for s in matching)
        if joined.strip():
            return joined[: settings.schema_max_text_chars]

    # No labeled match → fall back to whole document
    return _clean_text(md_content or plain_text)[: settings.schema_max_text_chars]


def _run_section_extraction(
    section_config: dict,
    document_type: str,
    sections: list[dict],
    md_content: str,
    plain_text: str,
    llm: LlmService,
    full_texts: list[dict] | None = None,
) -> dict:
    """Run one LLM extraction call for a section group. Returns field dict."""
    pf = section_config["prompt_file"]
    prompt_path = _PROMPT_DIR / pf
    if not prompt_path.exists():
        # Fallback: use generic extraction prompt with field hints
        prompt_path = _PROMPT_DIR / "schema_extraction.txt"

    prompt_template = prompt_path.read_text(encoding="utf-8")
    section_text = _collect_section_text(
        sections,
        section_config["labels"],
        md_content,
        plain_text,
        full_texts=full_texts,
    )

    full_prompt = (
        f"{prompt_template}\n\n"
        f"DOCUMENT_TYPE: {document_type}\n"
        f"EXTRACTION_TARGET:\n{section_config['fields']}\n\n"
        f"<SECTION_TEXT>\n{section_text}\n</SECTION_TEXT>"
    )

    raw = llm.small_model_call(
        prompt=full_prompt,
        system_message="Extract fields from this document section. Return JSON only.",
    )
    try:
        return _parse_json(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Section extraction JSON parse failed for %s", section_config["name"])
        return {}


def _merge_section_extracts(section_name: str, extracted: dict, master: dict) -> dict:
    """
    Merge section extract into the master schema dict.

    Upgrade rules:
      - missing       can be overwritten by extracted, low_confidence
      - low_confidence can be overwritten by extracted (higher confidence wins)
      - extracted     can be overwritten by extracted IF new confidence is higher
    """
    for key, val in extracted.items():
        if key in ("document", "vehicle", "profiles"):
            master.setdefault(key, {})
            _merge_section_extracts(key, val, master[key])
        elif isinstance(val, list) and key in master and isinstance(master[key], list):
            master[key].extend(val)
        elif isinstance(val, list):
            # New array field — set directly
            master[key] = val
        elif isinstance(val, dict) and "value" in val and "status" in val:
            existing = master.get(key)
            new_status = val.get("status")
            new_conf = float(val.get("confidence") or 0)
            if not isinstance(existing, dict) or "value" not in existing:
                master[key] = val
            else:
                existing_status = existing.get("status")
                existing_conf = float(existing.get("confidence") or 0)
                # Upgrade rules
                if existing_status == "missing" and new_status != "missing":
                    master[key] = val
                elif existing_status == "low_confidence" and new_status == "extracted":
                    master[key] = val
                elif existing_status == "extracted" and new_status == "extracted" and new_conf > existing_conf:
                    master[key] = val
                # Otherwise keep existing
        elif isinstance(val, dict):
            master.setdefault(key, {})
            if isinstance(master[key], dict):
                _merge_section_extracts(key, val, master[key])
        else:
            master.setdefault(key, val)
    return master


def extract_master_schema(
    document_id: str,
    document_type: str,
    md_content: str,
    plain_text: str,
    page_count: int | None,
    tables_text: str = "",
    sections: list[dict] | None = None,
) -> dict:
    """
    Run per-section extraction pipeline, merge into master schema, write to DB.
    Each section group emits its own pipeline event via the orchestrator's event step.
    Returns the merged master_schema dict.
    """
    if not settings.enable_schema_pipeline:
        return _empty_schema(document_type)

    llm = LlmService()
    sections = sections or []

    # Use combined text (tables_text first for table-heavy docs)
    effective_md = tables_text.strip() + "\n\n" + (md_content or "") if tables_text.strip() else (md_content or "")
    effective_md = _clean_text(effective_md)

    extraction_groups = SECTION_EXTRACTION_MAP.get(
        document_type, SECTION_EXTRACTION_MAP["generic_document"]
    )

    section_extracts = []
    master: dict = {
        "document": {},
        "vehicle": {},
        "profiles": {document_type: {}},
        "extensions": [],
    }

    for group in extraction_groups:
        logger.info("[%s] Extracting section group: %s", document_id, group["name"])
        extracted = _run_section_extraction(
            group, document_type, sections, effective_md, plain_text, llm
        )
        extracted = _normalize_field_wrappers_deep(extracted)

        # Store intermediate extract
        section_extracts.append({
            "name": group["name"],
            "labels": group["labels"],
            "extracted": extracted,
        })

        # Merge into master
        if group["name"] in ("vehicle_identification", "vehicle_and_header"):
            # Vehicle fields go into master.vehicle
            vehicle_fields = extracted.get("vehicle", extracted)
            _merge_section_extracts("vehicle", vehicle_fields, master["vehicle"])
            # Also pick up document-level fields
            doc_fields = extracted.get("document", {})
            _merge_section_extracts("document", doc_fields, master["document"])
            # Invoice header fields
            for inv_key in ("invoice_no", "ro_no", "invoice_date", "customer", "complaint", "correction"):
                if inv_key in extracted:
                    master["profiles"][document_type].setdefault(inv_key, extracted[inv_key])

        elif group["name"] in ("coverage_summary", "coverage_codes", "line_items", "exclusions", "claim_procedure"):
            profile = master["profiles"].setdefault(document_type, {})
            _merge_section_extracts(group["name"], extracted, profile)

        elif group["name"] == "full_document":
            _merge_section_extracts("document", extracted.get("document", {}), master["document"])
            _merge_section_extracts("vehicle", extracted.get("vehicle", {}), master["vehicle"])
            for ext in extracted.get("extensions", []):
                master["extensions"].append(ext)

    # Normalize all field wrappers to canonical status, then make/model/VIN
    master = _normalize_field_wrappers_deep(master)
    master = _normalize(master)

    # Quality
    quality = _compute_quality(master, page_count)
    master["quality"] = quality

    # Extract top-level vehicle values for DB columns
    vehicle = master.get("vehicle", {}) or {}
    make_val = _fw_value(vehicle.get("make"))
    model_val = _fw_value(vehicle.get("model"))
    year_val = _fw_value(vehicle.get("model_year"))
    vin_val = _fw_value(vehicle.get("vin"))
    chassis_val = _fw_value(vehicle.get("chassis_id"))

    # Required fields check — use shared helper that respects document_type
    from .required_fields import has_required_fields

    unit_val = _fw_value(vehicle.get("unit_number"))
    required_missing = not has_required_fields(
        vin_val, chassis_val, make_val, model_val, document_type, unit_val
    )

    with SessionLocal() as session:
        session.execute(
            text("""
                UPDATE documents
                SET master_schema_json       = CAST(:schema AS jsonb),
                    section_extracts_json    = CAST(:extracts AS jsonb),
                    completeness             = :comp,
                    required_fields_missing  = :req_missing,
                    make                     = COALESCE(:make, make),
                    model                    = COALESCE(:model, model),
                    year                     = COALESCE(:year, year),
                    metadata_json            = COALESCE(metadata_json, '{}'::jsonb)
                                               || CAST(:meta AS jsonb),
                    updated_at               = NOW()
                WHERE id = :id
            """),
            {
                "schema": json.dumps(master),
                "extracts": json.dumps(section_extracts),
                "comp": quality["overall_completeness"],
                "req_missing": required_missing,
                "make": make_val,
                "model": model_val,
                "year": year_val,
                "meta": json.dumps({k: v for k, v in {
                    "vin": vin_val, "chassis_id": chassis_val
                }.items() if v}),
                "id": document_id,
            },
        )
        session.commit()

    logger.info(
        "[%s] Schema extracted completeness=%.2f required_missing=%s groups=%d",
        document_id, quality["overall_completeness"], required_missing, len(section_extracts)
    )
    return master


def _normalize(schema: dict) -> dict:
    vehicle = schema.get("vehicle", {})
    if isinstance(vehicle, dict):
        # Make
        raw_make = _fw_value(vehicle.get("make")) or ""
        if raw_make.lower() in ("volvo", "volvo truck", "volvo trucks"):
            if isinstance(vehicle.get("make"), dict):
                vehicle["make"]["value"] = "Volvo Truck"

        # Model — strip trailing N
        raw_model = _fw_value(vehicle.get("model")) or ""
        if raw_model and isinstance(vehicle.get("model"), dict):
            vehicle["model"]["value"] = re.sub(r"\s+N$", "", str(raw_model)).strip()

        # VIN — uppercase + 17-char validation
        raw_vin = _fw_value(vehicle.get("vin"))
        if raw_vin and isinstance(vehicle.get("vin"), dict):
            vin_upper = str(raw_vin).strip().upper()
            if re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vin_upper) and sum(c.isdigit() for c in vin_upper) >= 2:
                vehicle["vin"]["value"] = vin_upper
            else:
                # Doesn't match VIN format or is all-letters — downgrade confidence
                vehicle["vin"]["value"] = vin_upper if vin_upper else None
                vehicle["vin"]["status"] = "low_confidence" if vin_upper else "missing"

        # model_year — coerce to int if string
        my_fw = vehicle.get("model_year")
        if isinstance(my_fw, dict) and isinstance(my_fw.get("value"), str):
            m = re.search(r"\b(19|20)\d{2}\b", my_fw["value"])
            if m:
                my_fw["value"] = int(m.group(0))
            else:
                my_fw["value"] = None
                my_fw["status"] = "missing"
    return schema


def _compute_quality(schema: dict, page_count: int | None) -> dict:
    extracted = missing = low_conf = 0
    unknown_statuses: list[str] = []

    def _walk(obj):
        nonlocal extracted, missing, low_conf
        if isinstance(obj, dict):
            if "status" in obj and "value" in obj:
                st = obj.get("status")
                if st == "extracted":
                    extracted += 1
                elif st == "low_confidence":
                    low_conf += 1
                    extracted += 1
                elif st == "missing":
                    missing += 1
                else:
                    unknown_statuses.append(str(st))
                    # Defensive: count as missing so we don't inflate completeness
                    missing += 1
            else:
                for v in obj.values():
                    _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(schema)
    if unknown_statuses:
        logger.warning("Unknown statuses after normalization: %s", list(set(unknown_statuses))[:10])

    total = extracted + missing
    return {
        "overall_completeness": round(extracted / total, 3) if total > 0 else 0.0,
        "fields_extracted": extracted,
        "fields_missing": missing,
        "fields_low_confidence": low_conf,
        "extraction_warnings": [f"unknown_status:{s}" for s in list(set(unknown_statuses))[:5]],
    }


def _empty_schema(document_type: str) -> dict:
    return {
        "document": {"document_type": {"value": document_type, "status": "extracted", "confidence": 0.5, "page": None}},
        "vehicle": {}, "profiles": {document_type: {}}, "extensions": [], "quality": {
            "overall_completeness": 0.0, "fields_extracted": 0, "fields_missing": 1,
            "fields_low_confidence": 0, "extraction_warnings": ["schema pipeline disabled"],
        },
    }
