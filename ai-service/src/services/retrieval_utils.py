"""Post-retrieval helpers for search quality."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from .warranty_code_utils import extract_warranty_codes

logger = logging.getLogger("retrieval_utils")


def wrap_scored_point(point: object, score: float | None = None) -> object:
    """Qdrant scroll Records are immutable; wrap as scored object for pipeline sorting."""
    payload = getattr(point, "payload", None) or {}
    base = float(getattr(point, "score", 0) or 0)
    final = base if score is None else float(score)
    try:
        point.score = final  # type: ignore[attr-defined]
        return point
    except (ValueError, AttributeError, TypeError):
        return SimpleNamespace(score=final, payload=payload)


def dedupe_search_results(points: list, top_k: int, max_per_doc_page: int = 2) -> list:
    out: list = []
    page_counts: dict[tuple, int] = {}
    text_sigs: set[tuple] = set()

    for point in points:
        p = point.payload or {}
        doc_page = (p.get("documentId"), p.get("pageNumber"))
        if page_counts.get(doc_page, 0) >= max_per_doc_page:
            continue

        sig = (p.get("documentId"), (p.get("chunkText") or "")[:180])
        if sig in text_sigs:
            continue

        text_sigs.add(sig)
        page_counts[doc_page] = page_counts.get(doc_page, 0) + 1
        out.append(point)
        if len(out) >= top_k:
            break

    return out


def _chunk_searchable_text(payload: dict) -> str:
    parts = [
        payload.get("chunkText") or "",
        payload.get("contextualizedText") or "",
        " ".join(payload.get("coverageCodes") or []),
    ]
    return " ".join(parts)


def lexical_match_bonus(payload: dict, codes: list[str], keywords: list[str]) -> float:
    """Score boost when chunk text or coverageCodes contain query codes/keywords."""
    if not payload:
        return 0.0
    text = _chunk_searchable_text(payload).upper()
    bonus = 0.0
    payload_codes = {str(c).upper() for c in (payload.get("coverageCodes") or [])}

    for code in codes:
        cu = code.upper()
        if cu in payload_codes:
            bonus += 3.0
        elif cu in text:
            bonus += 2.0

    for kw in keywords:
        ku = (kw or "").strip()
        if len(ku) < 3:
            continue
        if ku.upper() in text or ku.lower() in text.lower():
            bonus += 0.75

    return bonus


def rerank_with_lexical_boost(
    points: list,
    question: str,
    metadata: dict | None = None,
) -> list:
    """Re-sort hybrid results: RRF score + lexical code/keyword matches."""
    metadata = metadata or {}
    codes = list(metadata.get("warranty_codes") or [])
    if not codes:
        codes = extract_warranty_codes(question)
    keywords = list(metadata.get("semantic_keywords") or [])

    scored: list[tuple[float, object]] = []
    for point in points:
        base = float(getattr(point, "score", 0) or 0)
        bonus = lexical_match_bonus(point.payload or {}, codes, keywords)
        combined = base + bonus
        try:
            point.score = combined
        except (AttributeError, TypeError):
            pass
        scored.append((combined, point))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [point for _, point in scored]


def expand_parents_for_reasoning(chunks: list[dict]) -> list[dict]:
    """
    Deduplicate by parentChunkId; use parentChunkText for LLM, keep child snippet.
    Legacy chunks without parent fields pass through unchanged.
    """
    if not chunks:
        return chunks

    by_parent: dict[str, dict] = {}
    order: list[str] = []

    for item in chunks:
        payload = dict(item.get("payload") or {})
        parent_id = payload.get("parentChunkId") or payload.get("childChunkId")
        if not parent_id:
            key = f"legacy-{payload.get('documentId')}-{payload.get('chunkIndex')}-{id(payload)}"
            by_parent[key] = item
            order.append(key)
            continue

        child_snippet = payload.get("chunkText") or ""
        parent_text = payload.get("parentChunkText") or child_snippet
        score = float(item.get("score") or 0)

        if parent_id not in by_parent:
            expanded_payload = dict(payload)
            expanded_payload["retrievalSnippet"] = child_snippet
            expanded_payload["chunkText"] = parent_text
            by_parent[parent_id] = {"score": score, "payload": expanded_payload}
            order.append(parent_id)
        else:
            existing = by_parent[parent_id]
            existing["score"] = max(float(existing.get("score") or 0), score)

    out = [by_parent[k] for k in order if k in by_parent]
    if len(out) < len(chunks):
        logger.info("Parent expansion deduped %d -> %d chunks", len(chunks), len(out))
    return out
