"""Detect structured filter/compare queries and apply deterministic metadata filters."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("structured_query")

_STRUCTURED_RE = re.compile(
    r"\b("
    r"greater|less|more than|fewer than|above|below|exceed|at least|at most|"
    r"highest|lowest|longest|shortest|average|how many|"
    r"compare|comparison|after \d|before \d|expire|active until|remain active|"
    r"invalid|still apply|ordered by|list all|show all"
    r")\b",
    re.IGNORECASE,
)

_DURATION_RE = re.compile(
    r"(?:after|more than|greater than|exceed[s]?|over)\s+(\d+)\s*(?:years?|months?)",
    re.IGNORECASE,
)
_MILEAGE_RE = re.compile(
    r"(?:below|under|less than|before)\s+([\d,]+)\s*(?:miles?|mi)\b|"
    r"(?:above|over|more than|exceed[s]?)\s+([\d,]+)\s*(?:miles?|mi)\b",
    re.IGNORECASE,
)
_MONTHS_RE = re.compile(
    r"(?:more than|greater than|exceed[s]?|over)\s+(\d+)\s*months?",
    re.IGNORECASE,
)


def is_structured_query(question: str) -> bool:
    """True for comparisons, aggregations, inequalities, temporal filters."""
    q = question or ""
    if _STRUCTURED_RE.search(q):
        return True
    if re.search(r"\bwhich\b.+\b(longer|shorter|highest|lowest|most|least)\b", q, re.I):
        return True
    return False


def is_simple_retrieval_query(question: str) -> bool:
    """Direct lookup — skip structured engine."""
    q = (question or "").lower()
    if is_structured_query(question):
        return False
    if re.match(r"^what (is|does|are)\b", q):
        return True
    if re.search(r"\b(coverage code|warranty code|what does)\b", q):
        return True
    return len(q.split()) <= 12 and not re.search(r"\b(and|or|all|list|compare)\b", q)


def parse_structured_constraints(question: str) -> dict[str, Any]:
    """Lightweight constraint extraction from question text."""
    q = question or ""
    constraints: dict[str, Any] = {
        "min_duration_months": None,
        "max_duration_months": None,
        "min_mileage": None,
        "max_mileage": None,
        "engine_related": "engine" in q.lower() or "epa" in q.lower(),
        "transmission_related": "transmission" in q.lower() or "driveline" in q.lower(),
        "drivetrain_related": "drivetrain" in q.lower() or "driveline" in q.lower(),
        "epa_related": "epa" in q.lower(),
        "topic_any": [],
    }

    dm = _DURATION_RE.search(q)
    if dm:
        val = int(dm.group(1))
        unit = q.lower()[dm.end() : dm.end() + 12]
        months = val * 12 if "year" in unit else val
        if "after" in q.lower()[: dm.start()].lower() or "more than" in q.lower():
            constraints["min_duration_months"] = months

    mm = _MONTHS_RE.search(q)
    if mm:
        constraints["min_duration_months"] = int(mm.group(1))

    for m in _MILEAGE_RE.finditer(q):
        groups = [g for g in m.groups() if g]
        if not groups:
            continue
        miles = int(groups[0].replace(",", ""))
        span = q[max(0, m.start() - 20) : m.start()].lower()
        if any(w in span for w in ("below", "under", "less", "before")):
            constraints["max_mileage"] = miles
        else:
            constraints["min_mileage"] = miles

    if constraints["epa_related"]:
        constraints["topic_any"].append("epa")
    if constraints["engine_related"]:
        constraints["topic_any"].append("engine")
    if constraints["transmission_related"]:
        constraints["topic_any"].append("transmission")
    if constraints["drivetrain_related"]:
        constraints["topic_any"].append("drivetrain")

    return constraints


def _meta(chunk: dict) -> dict:
    payload = chunk.get("payload") or chunk
    return payload.get("structuredMeta") or {}


def apply_structured_filters(chunks: list[dict], constraints: dict[str, Any]) -> list[dict]:
    """Filter retrieved chunks using structuredMeta payload fields."""
    if not constraints:
        return chunks

    out: list[dict] = []
    for item in chunks:
        meta = _meta(item)
        if not meta:
            out.append(item)
            continue

        months = meta.get("duration_months")
        miles = meta.get("mileage_limit")
        if meta.get("unlimited_mileage"):
            miles = 10**9

        if constraints.get("min_duration_months") is not None:
            if months is None or months < constraints["min_duration_months"]:
                continue
        if constraints.get("max_duration_months") is not None:
            if months is None or months > constraints["max_duration_months"]:
                continue
        if constraints.get("min_mileage") is not None:
            if miles is None or miles < constraints["min_mileage"]:
                continue
        if constraints.get("max_mileage") is not None:
            if miles is None or miles > constraints["max_mileage"]:
                continue

        if constraints.get("engine_related") and not meta.get("engine_related"):
            continue
        if constraints.get("transmission_related") and not meta.get("transmission_related"):
            if not meta.get("drivetrain_related"):
                continue
        if constraints.get("drivetrain_related") and not meta.get("drivetrain_related"):
            continue

        out.append(item)

    logger.info(
        "Structured filter kept %d/%d chunks constraints=%s",
        len(out),
        len(chunks),
        {k: v for k, v in constraints.items() if v not in (None, False, [])},
    )
    return out if out else chunks
