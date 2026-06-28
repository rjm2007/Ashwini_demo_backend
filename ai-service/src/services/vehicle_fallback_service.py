"""
When Docling / Act 1 text does not yield VIN, make, and model, run regex + LLM
on the full document text before asking a reviewer to fill the form manually.
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
from ..services.schema_extraction_service import _clean_text, _merge_section_extracts
from ..services.ocr_service import OcrService
from ..services.strategic_chunker import parse_vin_chassis_from_text
from ..services.invoice_header_parser import parse_invoice_header, looks_like_invoice
from ..services.required_fields import has_required_fields

logger = logging.getLogger("vehicle_fallback")
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "extract_vehicle_required.txt"
_VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b", re.IGNORECASE)


def _is_valid_vin(value) -> bool:
    """A real VIN is 17 chars from [A-HJ-NPR-Z0-9] AND contains digits.
    Rejects all-letter strings like 'CRANKCASEPRESSURE'."""
    if not value:
        return False
    v = str(value).strip().upper()
    if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", v):
        return False
    return sum(c.isdigit() for c in v) >= 2

_MAKE_HINTS = re.compile(
    r"\b(Volvo\s+Truck[s]?|Freightliner|Kenworth|Peterbilt|Mack|International)\b",
    re.IGNORECASE,
)
_MODEL_HINTS = re.compile(
    r"\b(VNL\d{2,4}[A-Z]?|Cascadia|579|W900|T680|Anthem)\b",
    re.IGNORECASE,
)
_YEAR_HINTS = re.compile(r"\b(19|20)\d{2}\b")


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


def _wrap(value: Any, *, source: str = "llm", confidence: float = 0.85) -> dict:
    if value is None or (isinstance(value, str) and not value.strip()):
        return {
            "value": None,
            "status": "missing",
            "confidence": 0.0,
            "page": None,
            "evidence_quote": None,
        }
    return {
        "value": value,
        "status": "extracted",
        "confidence": confidence,
        "page": None,
        "evidence_quote": f"vehicle_fallback:{source}",
    }


def _has_required_fields(vehicle: dict, document_type: str = "") -> bool:
    return has_required_fields(
        _fw_value(vehicle.get("vin")),
        _fw_value(vehicle.get("chassis_id")),
        _fw_value(vehicle.get("make")),
        _fw_value(vehicle.get("model")),
        document_type,
        _fw_value(vehicle.get("unit_number")),
    )


def _build_document_text(structured: dict, extra_text: str = "") -> str:
    """Use Docling text items + tables — never raw md with embedded images."""
    readable = _clean_text(
        structured.get("readable_text")
        or structured.get("plain_text")
        or ""
    )
    tables = (structured.get("tables_text") or "").strip()
    parts: list[str] = []
    if readable:
        parts.append(f"<READABLE_TEXT>\n{readable}\n</READABLE_TEXT>")
    if tables:
        parts.append(f"<TABLES>\n{tables}\n</TABLES>")
    if extra_text.strip():
        parts.append(f"<OCR_SUPPLEMENT>\n{extra_text.strip()}\n</OCR_SUPPLEMENT>")
    return "\n\n".join(parts)[: settings.schema_max_text_chars]


def _parse_sequence_labels(text: str) -> dict:
    """Pair OCR UI labels with values (Volvo VDA screens)."""
    vehicle: dict = {}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        norm = re.sub(r"[^a-z0-9]", "", line.lower())
        if norm in ("volvotruck", "volvotrucks", "volvo"):
            vehicle["make"] = _wrap("Volvo Truck", source="sequence", confidence=0.9)
        if norm in ("ovin", "vin", "oregno") and i + 1 < len(lines):
            nxt = re.sub(r"\s+", "", lines[i + 1].upper())
            if _VIN_RE.fullmatch(nxt) and _is_valid_vin(nxt):
                vehicle["vin"] = _wrap(nxt, source="sequence", confidence=0.95)
        if ("chassis" in norm or norm == "nr") and i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if re.fullmatch(r"\d{5,8}", nxt):
                vehicle["chassis_id"] = _wrap(nxt, source="sequence", confidence=0.9)
        if "unitnumber" in norm and i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if re.fullmatch(r"[A-Z0-9]{4,12}", nxt, re.I):
                vehicle.setdefault("unit_number", _wrap(nxt, source="sequence", confidence=0.75))

    for m in _VIN_RE.finditer(text):
        cand = m.group(1).upper()
        if "vin" not in vehicle and _is_valid_vin(cand):
            vehicle["vin"] = _wrap(cand, source="regex", confidence=0.95)
            break

    if "VolvoTruck" in text or "Volvo Truck" in text:
        vehicle.setdefault("make", _wrap("Volvo Truck", source="regex", confidence=0.85))

    m = re.search(r"Marketing\s*type\s*([A-Z0-9]{2,12})", text, re.I)
    if m and "model" not in vehicle:
        vehicle["model"] = _wrap(m.group(1).upper(), source="sequence", confidence=0.8)

    return vehicle


def _ocr_supplement_text(s3_path: str | None) -> str:
    if not s3_path:
        return ""
    try:
        result = OcrService().run_ocr(s3_path)
        pages = result.get("pages") or []
        return "\n".join(p.get("text", "") for p in pages if p.get("text"))
    except Exception as exc:
        logger.warning("OCR supplement failed: %s", exc)
        return ""


def _regex_vehicle_hints(text: str) -> dict:
    """Fast pass: VIN/chassis regex + simple make/model/year patterns."""
    vehicle: dict = {}
    parsed = parse_vin_chassis_from_text(text[:15000])
    if not parsed.get("vin"):
        for m in re.finditer(r"\b([A-HJ-NPR-Z0-9]{17})\b", text, re.IGNORECASE):
            cand = m.group(1).upper()
            if _is_valid_vin(cand):
                parsed["vin"] = cand
                break
    if not parsed.get("chassis_id"):
        for m in re.finditer(
            r"(?:Chassis|Unit)\s*(?:ID|No\.?|#)?\s*(?:NR?\.?\s*)?(\d{5,8})",
            text,
            re.IGNORECASE,
        ):
            parsed["chassis_id"] = m.group(1)
            break
    if parsed.get("vin") and _is_valid_vin(parsed["vin"]):
        vehicle["vin"] = _wrap(parsed["vin"], source="regex", confidence=0.95)
    if parsed.get("chassis_id"):
        vehicle["chassis_id"] = _wrap(parsed["chassis_id"], source="regex", confidence=0.9)

    make_m = _MAKE_HINTS.search(text[:20000])
    if make_m:
        make_val = make_m.group(1)
        if make_val.lower().startswith("volvo"):
            make_val = "Volvo Truck"
        vehicle["make"] = _wrap(make_val, source="regex", confidence=0.8)

    model_m = _MODEL_HINTS.search(text[:20000])
    if model_m:
        vehicle["model"] = _wrap(model_m.group(1), source="regex", confidence=0.75)

    year_m = _YEAR_HINTS.search(text[:20000])
    if year_m:
        vehicle["model_year"] = _wrap(int(year_m.group(0)), source="regex", confidence=0.7)

    return vehicle


def _llm_vehicle_extract(document_id: str, doc_text: str) -> dict:
    if not doc_text.strip():
        return {}
    llm = LlmService()
    prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    full_prompt = (
        f"{prompt}\n\n"
        "CONTEXT: Initial PDF parsing did not find all required vehicle fields. "
        "Search the ENTIRE document text below for VIN, Chassis ID, Make, Model, and Year.\n\n"
        f"{doc_text}"
    )
    raw = llm.small_model_call(
        prompt=full_prompt,
        system_message=(
            "Extract vehicle identification fields from warranty/invoice PDF text. "
            "Return JSON only. Use evidence from the text; do not guess."
        ),
    )
    try:
        return _parse_json(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("[%s] Vehicle LLM fallback JSON parse failed", document_id)
        return {}


def _normalize_make(vehicle: dict) -> None:
    make_fw = vehicle.get("make")
    if not isinstance(make_fw, dict):
        return
    raw = str(_fw_value(make_fw) or "")
    if raw.lower() in ("volvo", "volvo truck", "volvo trucks"):
        make_fw["value"] = "Volvo Truck"


def run_vehicle_fallback(
    document_id: str,
    structured: dict,
    document_type: str,
    s3_path: str | None = None,
) -> dict:
    """
    Try to populate required vehicle fields before awaiting_certification.
    Returns summary dict for pipeline event detail.
    """
    readable = (
        structured.get("readable_text")
        or _clean_text(structured.get("plain_text") or "")
    )
    ocr_extra = ""
    ocr_extra = ""
    if not _VIN_RE.search(readable) and s3_path:
        ocr_extra = _ocr_supplement_text(s3_path)

    doc_text = _build_document_text(structured, ocr_extra)
    scan_text = "\n".join(filter(None, [readable, structured.get("tables_text") or "", ocr_extra]))

    vehicle: dict = {}
    document_hdr: dict = {}
    sources: list[str] = []

    seq_vehicle = _parse_sequence_labels(scan_text)
    if seq_vehicle:
        _merge_section_extracts("vehicle", seq_vehicle, vehicle)
        sources.append("sequence")

    regex_vehicle = _regex_vehicle_hints(scan_text)
    if regex_vehicle:
        _merge_section_extracts("vehicle", regex_vehicle, vehicle)
        sources.append("regex")

    if ocr_extra:
        sources.append("ocr")

    # FIX 5: Invoice self-identification in Act 1 (deterministic, no LLM)
    if looks_like_invoice(scan_text) and not (_fw_value(vehicle.get("vin")) or _fw_value(vehicle.get("chassis_id"))):
        inv = parse_invoice_header(scan_text)
        if inv.get("unit_number"):
            vehicle.setdefault("unit_number", inv["unit_number"])
        if inv.get("make") and not vehicle.get("make"):
            vehicle["make"] = inv["make"]
        if inv.get("model") and not vehicle.get("model"):
            vehicle["model"] = inv["model"]
        iv = _fw_value(inv.get("vin"))
        if iv and _is_valid_vin(iv) and not vehicle.get("vin"):
            vehicle["vin"] = inv["vin"]
        sources.append("invoice_header")

    if not _has_required_fields(vehicle, document_type) and settings.enable_vehicle_llm_fallback:
        llm_result = _llm_vehicle_extract(document_id, doc_text or scan_text)
        if llm_result.get("vehicle"):
            _merge_section_extracts("vehicle", llm_result["vehicle"], vehicle)
            sources.append("llm")
        if llm_result.get("document"):
            _merge_section_extracts("document", llm_result["document"], document_hdr)

    _normalize_make(vehicle)

    required_missing = not _has_required_fields(vehicle, document_type)
    _persist(document_id, vehicle, document_hdr, document_type, required_missing)

    logger.info(
        "[%s] Vehicle fallback sources=%s required_missing=%s vin=%s make=%s model=%s",
        document_id,
        sources or ["none"],
        required_missing,
        _fw_value(vehicle.get("vin")),
        _fw_value(vehicle.get("make")),
        _fw_value(vehicle.get("model")),
    )

    return {
        "sources": sources,
        "required_missing": required_missing,
        "vin": _fw_value(vehicle.get("vin")),
        "chassis_id": _fw_value(vehicle.get("chassis_id")),
        "make": _fw_value(vehicle.get("make")),
        "model": _fw_value(vehicle.get("model")),
        "year": _fw_value(vehicle.get("model_year")),
    }


def _persist(
    document_id: str,
    vehicle: dict,
    document_hdr: dict,
    document_type: str,
    required_missing: bool,
) -> None:
    master = {
        "document": document_hdr,
        "vehicle": vehicle,
        "profiles": {document_type: {}},
        "extensions": [],
        "quality": {
            "overall_completeness": 0.0,
            "fields_extracted": 0,
            "fields_missing": 0,
            "fields_low_confidence": 0,
            "extraction_warnings": ["act1_vehicle_fallback"],
            "page_count": None,
            "tables_detected": 0,
        },
    }

    meta_patch = {
        k: v
        for k, v in {
            "vin": _fw_value(vehicle.get("vin")),
            "chassis_id": _fw_value(vehicle.get("chassis_id")),
            "unit_number": _fw_value(vehicle.get("unit_number")),
        }.items()
        if v
    }

    with SessionLocal() as session:
        session.execute(
            text("""
                UPDATE documents
                SET master_schema_json = COALESCE(master_schema_json, '{}'::jsonb)
                    || CAST(:partial AS jsonb),
                    make = COALESCE(:make, make),
                    model = COALESCE(:model, model),
                    year = COALESCE(:year, year),
                    metadata_json = COALESCE(metadata_json, '{}'::jsonb) || CAST(:meta AS jsonb),
                    required_fields_missing = :req,
                    updated_at = NOW()
                WHERE id = :id
            """),
            {
                "partial": json.dumps(master),
                "make": _fw_value(vehicle.get("make")),
                "model": _fw_value(vehicle.get("model")),
                "year": _fw_value(vehicle.get("model_year")),
                "meta": json.dumps(meta_patch),
                "req": required_missing,
                "id": document_id,
            },
        )
        session.commit()
