# ai-service/src/services/aggregation_engine.py
"""Deterministic corpus-wide aggregation over CERTIFIED Qdrant chunks.

Vector RAG cannot count or group reliably: top-k + per-page dedupe drop most
coverage rows. For "how many" / count / group-by / "all vehicles" questions we
scroll EVERY certified chunk, rebuild per-document facts, and compute the answer
in code — bypassing the LLM reasoning path entirely.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any

from qdrant_client.models import FieldCondition, Filter, MatchValue

from .qdrant_service import QdrantService

logger = logging.getLogger("aggregation_engine")

# --- intent detection -------------------------------------------------------

_COUNT_RE = re.compile(r"\b(how many|number of|count|total)\b", re.IGNORECASE)
_GROUP_RE = re.compile(r"\b(?:by|per)\s+(make|model|year|model\s*year|vehicle|vin|chassis)\b", re.IGNORECASE)
_ALL_RE = re.compile(r"\ball\s+(vehicles?|trucks?|warranties|coverages?|documents?)\b", re.IGNORECASE)
_WARRANTY_WORD_RE = re.compile(r"\b(warrant\w*|coverage\w*|vehicle\w*|truck\w*|document\w*)\b", re.IGNORECASE)
_EXCLUSION_RE = re.compile(r"\b(excluded?|not covered|exclusions?|what is not)\b", re.IGNORECASE)

# VIN / chassis extraction from question
_VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")
_CHASSIS_RE = re.compile(r"(?:chassis|unit)\s*(?:ID)?\s*(?:NR?)?\s*(\d{5,6})\b", re.IGNORECASE)

# authoritative count printed by the VDA+ export, e.g. "(1 to 26 of 26)"
_AUTH_COUNT_RE = re.compile(r"\(1\s*to\s*\d+\s*of\s*(\d+)\)", re.IGNORECASE)

# VIN position 10 (index 9) → model year
_VIN_YEAR = {
    "A": 2010, "B": 2011, "C": 2012, "D": 2013, "E": 2014, "F": 2015,
    "G": 2016, "H": 2017, "J": 2018, "K": 2019, "L": 2020, "M": 2021,
    "N": 2022, "P": 2023, "R": 2024, "S": 2025, "T": 2026,
}


def is_aggregation_query(question: str) -> bool:
    """True for count / group-by / all-vehicles / exclusion questions that need a full scan."""
    q = question or ""
    if _EXCLUSION_RE.search(q):
        return True
    if _GROUP_RE.search(q):
        return True
    if _COUNT_RE.search(q) and _WARRANTY_WORD_RE.search(q):
        return True
    if _ALL_RE.search(q) and _COUNT_RE.search(q):
        return True
    return False


def _detect_group_key(question: str) -> str | None:
    q = (question or "").lower()
    has_year = bool(re.search(r"\byear\b", q))
    has_make = bool(re.search(r"\bmake\b", q))
    has_model = bool(re.search(r"\bmodel\b", q))
    has_vehicle = bool(re.search(r"\b(vehicle|vin|chassis)\b", q))

    if has_year:
        return "year"
    if has_vehicle:
        return "vehicle"
    if has_model:
        return "model"
    if has_make:
        return "make"
    return None


def _extract_scope(question: str) -> dict:
    """Extract VIN or chassis from question to scope aggregation to one vehicle."""
    scope: dict = {}
    vin_match = _VIN_RE.search(question or "")
    if vin_match:
        scope["vin"] = vin_match.group(1)
    chassis_match = _CHASSIS_RE.search(question or "")
    if chassis_match:
        scope["chassisId"] = chassis_match.group(1)
    return scope


def _decode_vin_year(vin: str | None) -> int | None:
    if not vin or len(vin) < 10:
        return None
    return _VIN_YEAR.get(vin[9].upper())


# --- scrolling --------------------------------------------------------------

def _scroll_certified(qdrant: QdrantService) -> list[dict]:
    """Page through ALL certified chunk payloads (no top-k, no dedupe)."""
    must = [FieldCondition(key="repository", match=MatchValue(value="certified"))]
    scroll_filter = Filter(must=must)
    payloads: list[dict] = []
    offset = None
    pages = 0
    while True:
        points, offset = qdrant.client.scroll(
            collection_name=qdrant.collection,
            scroll_filter=scroll_filter,
            limit=256,
            offset=offset,
            with_payload=True,
        )
        payloads.extend((p.payload or {}) for p in points)
        pages += 1
        if offset is None or pages > 200:  # safety cap
            break
    logger.info("Aggregation scroll: %d certified chunks", len(payloads))
    return payloads


# --- per-document fact building --------------------------------------------

def _build_documents(payloads: list[dict]) -> dict[str, dict[str, Any]]:
    docs: dict[str, dict[str, Any]] = {}
    for p in payloads:
        doc_id = p.get("documentId")
        if not doc_id:
            continue
        d = docs.setdefault(
            doc_id,
            {
                "documentId": doc_id,
                "vin": None,
                "chassisId": None,
                "make": None,
                "model": None,
                "year": None,
                "filename": None,
                "codes": set(),       # distinct coverage codes seen
                "row_chunks": 0,      # coverage_table child chunks (rows)
                "authoritative": None,  # from "(1 to N of N)"
            },
        )
        # identity fields (first non-null wins)
        for k in ("vin", "chassisId", "make", "model", "year", "filename"):
            if not d.get(k) and p.get(k):
                d[k] = p.get(k)
        # coverage codes + row count
        for c in (p.get("coverageCodes") or []):
            d["codes"].add(str(c).upper())
        if p.get("chunkType") == "coverage_table":
            d["row_chunks"] += 1
        # authoritative count from any chunk text
        text = p.get("chunkText") or ""
        m = _AUTH_COUNT_RE.search(text)
        if m:
            try:
                d["authoritative"] = max(d["authoritative"] or 0, int(m.group(1)))
            except ValueError:
                pass

    # derive year from VIN when metadata year missing
    for d in docs.values():
        if not d.get("year"):
            d["year"] = _decode_vin_year(d.get("vin"))
    return docs


def _filter_docs_by_scope(docs: dict[str, dict], scope: dict) -> dict[str, dict]:
    """Filter documents by VIN or chassis scope. Returns matching subset."""
    if not scope:
        return docs
    filtered = {}
    for doc_id, d in docs.items():
        if "vin" in scope and d.get("vin") == scope["vin"]:
            filtered[doc_id] = d
        elif "chassisId" in scope and d.get("chassisId") == scope["chassisId"]:
            filtered[doc_id] = d
    return filtered if filtered else docs  # fallback to all if no match


def _doc_count(d: dict) -> int:
    """Best available coverage-item count for one document."""
    if d.get("authoritative"):
        return int(d["authoritative"])
    if d.get("row_chunks"):
        return int(d["row_chunks"])
    return len(d.get("codes") or set())


def _label(d: dict) -> str:
    vin = d.get("vin") or "VIN?"
    chassis = d.get("chassisId")
    return f"{vin}" + (f" (chassis {chassis})" if chassis else "")


# --- public entrypoint ------------------------------------------------------

def aggregate(question: str) -> dict:
    """Return a query_orchestrator-compatible answer dict for aggregation queries."""
    qdrant = QdrantService()
    payloads = _scroll_certified(qdrant)
    all_docs = _build_documents(payloads)

    if not all_docs:
        return {
            "answer": "I don't see any certified warranty documents to count yet.",
            "evidence": [], "confidence": 0.3, "filters": {},
            "intent": "aggregation_query", "coverageDecision": "insufficient_evidence",
        }

    # Scope to a specific VIN or chassis if mentioned in the question
    scope = _extract_scope(question)
    docs = _filter_docs_by_scope(all_docs, scope)
    is_scoped = bool(scope) and len(docs) < len(all_docs)

    # ---- exclusion question ----
    if _EXCLUSION_RE.search(question):
        return _wrap(
            "These warranty exports list covered items only and contain no "
            "exclusion section. Exclusions, if any, are defined in the master "
            "Volvo warranty policy document, not in these VDA+ coverage exports.",
            docs,
        )

    group_key = _detect_group_key(question)
    total_docs = len(docs)
    total_items = sum(_doc_count(d) for d in docs.values())

    # ---- single-vehicle scoped answer ----
    if is_scoped and total_docs == 1:
        d = list(docs.values())[0]
        scope_label = scope.get("vin") or f"chassis {scope.get('chassisId')}"
        answer = (
            f"{scope_label} has {_doc_count(d)} coverage items in its certified "
            f"warranty document."
        )
        return _wrap(answer, docs)

    # ---- group-by answer ----
    if group_key in ("make", "model", "year"):
        buckets: dict[Any, list[dict]] = defaultdict(list)
        for d in docs.values():
            buckets[d.get(group_key) or "Unknown"].append(d)
        lines = [f"Grouped by {group_key}:"]
        for key in sorted(buckets, key=lambda x: str(x)):
            group_docs = buckets[key]
            items = sum(_doc_count(d) for d in group_docs)
            lines.append(f"- {key}: {len(group_docs)} vehicle(s), {items} coverage items")
        lines.append(f"\nTotal: {total_docs} vehicles, {total_items} coverage items.")
        return _wrap("\n".join(lines), docs)

    if group_key == "vehicle":
        lines = ["Coverage items per vehicle:"]
        for d in sorted(docs.values(), key=lambda x: str(x.get("vin"))):
            lines.append(f"- {_label(d)}: {_doc_count(d)} coverage items")
        lines.append(f"\nTotal: {total_docs} vehicles, {total_items} coverage items.")
        return _wrap("\n".join(lines), docs)

    # ---- plain count / "how many" / "all vehicles" ----
    lines = [
        f"There are {total_docs} certified warranty documents (one per vehicle), "
        f"with {total_items} coverage items in total.",
        "",
        "Per vehicle:",
    ]
    for d in sorted(docs.values(), key=lambda x: str(x.get("vin"))):
        lines.append(f"- {_label(d)}: {_doc_count(d)} coverage items")
    return _wrap("\n".join(lines), docs)


def _wrap(answer: str, docs: dict[str, dict]) -> dict:
    return {
        "answer": answer,
        "evidence": [],
        "confidence": 0.9,
        "filters": {"repository": "certified"},
        "intent": "aggregation_query",
        "coverageDecision": "n/a",
        "aggregation": {
            "documents": len(docs),
            "perDocument": [
                {
                    "vin": d.get("vin"),
                    "chassisId": d.get("chassisId"),
                    "year": d.get("year"),
                    "count": _doc_count(d),
                }
                for d in docs.values()
            ],
        },
    }
