import json
import logging
import re
from pathlib import Path

from ..services.llm_service import LlmService
from ..services.warranty_code_utils import enrich_metadata_with_codes

logger = logging.getLogger("metadata_filter")

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# --- VIN / Chassis regex for question text ---

_VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")
_CHASSIS_RE = re.compile(
    r"\bchassis\s+(?:ID\s+)?(?:NR?\.?\s*)?(\d{5,6})\b",
    re.IGNORECASE,
)


def extract_vin_chassis_from_question(question: str) -> dict:
    """Regex fallback: extract VIN and chassis ID(s) from question text."""
    result: dict = {"vin": None, "chassis_id": None, "vins": [], "chassis_ids": []}
    vins = list(dict.fromkeys(_VIN_RE.findall(question)))
    if vins:
        result["vins"] = vins
        result["vin"] = vins[0] if len(vins) == 1 else None
    chassis_ids = list(dict.fromkeys(_CHASSIS_RE.findall(question)))
    if chassis_ids:
        result["chassis_ids"] = chassis_ids
        result["chassis_id"] = chassis_ids[0] if len(chassis_ids) == 1 else None
    return result


def extract_metadata_filters(question: str, conversation_history: list[dict] | None = None) -> dict:
    """Extract Qdrant filters, query rewrite, and BM25 keywords (small model)."""
    llm = LlmService()
    prompt = (_PROMPTS_DIR / "query_metadata_extraction.txt").read_text(encoding="utf-8")

    history_block = ""
    if conversation_history:
        lines = [
            f"{item.get('role', 'user')}: {item.get('content', '')}"
            for item in conversation_history[-6:]
        ]
        history_block = "\nCONVERSATION HISTORY:\n" + "\n".join(lines)

    output = llm.small_model_call(
        f"{prompt}{history_block}\n\nUSER QUESTION: {question}",
        "Extract metadata filters. Return JSON only.",
    )
    try:
        payload = json.loads(output)
        if isinstance(payload, dict):
            # Regex fallback for VIN/chassis the LLM may have missed
            regex_vc = extract_vin_chassis_from_question(question)
            if not payload.get("vin") and regex_vc["vin"]:
                payload["vin"] = regex_vc["vin"]
            if regex_vc.get("vins"):
                payload["vins"] = regex_vc["vins"]
            if not payload.get("chassis_id") and regex_vc["chassis_id"]:
                payload["chassis_id"] = regex_vc["chassis_id"]
            if regex_vc.get("chassis_ids"):
                payload["chassis_ids"] = regex_vc["chassis_ids"]
            return enrich_metadata_with_codes(payload, question)
    except json.JSONDecodeError:
        logger.warning("Metadata filter JSON parse failed")

    fallback = {
        "make": None,
        "model": None,
        "year": None,
        "rewritten_query": question,
        "semantic_keywords": [],
        "component_synonyms": [],
        "extraction_confidence": 0.0,
    }
    regex_vc = extract_vin_chassis_from_question(question)
    if regex_vc.get("vin"):
        fallback["vin"] = regex_vc["vin"]
    if regex_vc.get("vins"):
        fallback["vins"] = regex_vc["vins"]
    if regex_vc.get("chassis_id"):
        fallback["chassis_id"] = regex_vc["chassis_id"]
    if regex_vc.get("chassis_ids"):
        fallback["chassis_ids"] = regex_vc["chassis_ids"]
    return enrich_metadata_with_codes(fallback, question)


# Minimum and maximum plausible truck model years.
# Years outside this range are almost certainly misextracted from mileage numbers,
# dates, or other numeric tokens in the query. We drop them to avoid false-zero results.
_MIN_VEHICLE_YEAR = 1980
_MAX_VEHICLE_YEAR = 2030


def _is_valid_year(value) -> bool:
    """Return True only when value is an integer that looks like a real model year."""
    if value is None:
        return False
    try:
        y = int(value)
        return _MIN_VEHICLE_YEAR <= y <= _MAX_VEHICLE_YEAR
    except (TypeError, ValueError):
        return False


def _normalize_make(make: str | None) -> str | None:
    """Canonical make for Qdrant exact-match filtering."""
    if not make:
        return None
    low = make.strip().lower()
    if low in ("volvo", "volvo truck", "volvo trucks"):
        return "Volvo Truck"
    return make.strip()


def _normalize_model(model: str | None) -> str | None:
    """Strip variant suffixes like ' N' for consistent Qdrant matching."""
    if not model:
        return None
    return re.sub(r"\s+N$", "", model.strip()).strip() or None


def qdrant_filters_from_metadata(metadata: dict) -> dict:
    """Map extraction JSON to Qdrant payload filter keys."""
    filters: dict = {}

    if metadata.get("make"):
        filters["make"] = _normalize_make(metadata["make"])

    if metadata.get("model"):
        filters["model"] = _normalize_model(metadata["model"])

    # Only apply year filter when the extracted year is a plausible vehicle model year.
    # Values like 2000, 200000, or 312000 that the LLM might confuse with mileage numbers
    # are rejected here so they do not create an AND filter that returns zero chunks.
    raw_year = metadata.get("year")
    # Reinforcement: if mileage is set and year looks derived from it, drop year
    raw_mileage = metadata.get("mileage")
    if raw_mileage and raw_year:
        try:
            if int(raw_year) == int(raw_mileage) // 100:
                raw_year = None
                logger.info("Year dropped — appears derived from mileage %s", raw_mileage)
        except (TypeError, ValueError):
            pass
    if _is_valid_year(raw_year):
        filters["year"] = int(raw_year)
    # If year is invalid or out of range, we silently drop it — do not add to filters.
    # The semantic search will still find the right document via embeddings.

    if metadata.get("country"):
        filters["country"] = metadata["country"]

    # VIN / chassis filters (single identifier only — comparisons use hybrid search)
    if metadata.get("vin"):
        filters["vin"] = metadata["vin"]

    chassis_ids = list(metadata.get("chassis_ids") or [])
    if not chassis_ids:
        single = metadata.get("chassis_id") or metadata.get("chassisId")
        if single:
            chassis_ids = [str(single)]
    if len(chassis_ids) == 1:
        filters["chassisId"] = str(chassis_ids[0])
    elif len(chassis_ids) > 1:
        logger.info(
            "Multiple chassis in question — skipping chassisId filter: %s",
            chassis_ids,
        )

    # warrantyType is rarely on chunk payloads; never AND-filter when VIN/chassis pin the doc
    warranty_type = metadata.get("warranty_type") or metadata.get("warrantyType")
    if warranty_type and not filters.get("vin") and not filters.get("chassisId"):
        filters["warrantyType"] = warranty_type

    # Document-scoped query: documentId overrides all other filters
    if metadata.get("_document_id"):
        filters["documentId"] = metadata["_document_id"]

    return filters
