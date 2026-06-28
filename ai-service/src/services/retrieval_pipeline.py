"""Production retrieval orchestration: hybrid search + quality + parent expansion."""

from __future__ import annotations

import logging
from typing import Any

from openai import OpenAI
from ..config import settings
from ..query.metadata_filter import qdrant_filters_from_metadata
from .coverage_row_parser import parse_chunk_structured_meta
from .qdrant_service import QdrantService
from .reranker_service import is_list_or_filter_question, rerank_points
from .retrieval_utils import (
    dedupe_search_results,
    expand_parents_for_reasoning,
    rerank_with_lexical_boost,
    wrap_scored_point,
)
from .sparse_encoder import BM25SparseEncoder
from .structured_query_engine import apply_structured_filters, is_structured_query, is_simple_retrieval_query, parse_structured_constraints
from .warranty_code_utils import enrich_metadata_with_codes, extract_warranty_codes

logger = logging.getLogger("retrieval_pipeline")


def _sparse_query_text(question: str, metadata: dict) -> str:
    parts = [
        question,
        metadata.get("rewritten_query") or "",
        metadata.get("component") or "",
        " ".join(metadata.get("component_synonyms") or []),
        " ".join(metadata.get("semantic_keywords") or []),
        metadata.get("defect_or_symptom") or "",
    ]
    return " ".join(p for p in parts if p).strip()


def _apply_score_threshold(points: list, threshold: float) -> tuple[list, list]:
    kept, rejected = [], []
    for pt in points:
        score = float(getattr(pt, "score", 0) or 0)
        if score < threshold:
            rejected.append(pt)
        else:
            kept.append(pt)
    if rejected:
        logger.info("Score threshold %.4f rejected %d chunks", threshold, len(rejected))
    return kept if kept else points


def _code_fast_path_lookup(
    qdrant: QdrantService,
    codes: list[str],
    filters: dict,
    limit: int = 15,
) -> list:
    """Scroll certified chunks matching coverage codes in payload."""
    if not codes:
        return []
    base_filter = qdrant._build_filter(filters)
    try:
        points, _ = qdrant.client.scroll(
            collection_name=qdrant.collection,
            scroll_filter=base_filter,
            limit=200,
            with_payload=True,
        )
    except Exception as exc:
        logger.warning("Code fast-path scroll failed: %s", exc)
        return []

    code_set = {c.upper() for c in codes}
    hits = []
    for pt in points:
        payload = pt.payload or {}
        payload_codes = {str(c).upper() for c in (payload.get("coverageCodes") or [])}
        text = (payload.get("chunkText") or "").upper()
        if payload_codes & code_set or any(c in text for c in code_set):
            hits.append(wrap_scored_point(pt, 10.0 + len(payload_codes & code_set)))
    hits.sort(key=lambda p: float(getattr(p, "score", 0) or 0), reverse=True)
    logger.info("Code fast-path found %d hits for codes=%s", len(hits[:limit]), codes[:5])
    return hits[:limit]


def _hybrid_fetch(
    question: str,
    metadata: dict,
    filters: dict,
    fetch_k: int,
    sparse_heavy: bool = False,
) -> list:
    qdrant = QdrantService()
    dense_query = (metadata.get("rewritten_query") or question).strip()
    client = OpenAI(api_key=settings.openai_api_key)
    embedding = client.embeddings.create(
        model="text-embedding-3-small",
        input=[dense_query],
    ).data[0].embedding

    sparse_text = _sparse_query_text(question, metadata)
    if sparse_heavy:
        sparse_text = f"{sparse_text} {question} {' '.join(metadata.get('warranty_codes') or [])}"

    if qdrant.hybrid:
        sparse_enc = BM25SparseEncoder(vocab_size=settings.bm25_vocab_size)
        sparse_vec = sparse_enc.encode(sparse_text)
        return qdrant.hybrid_search(
            dense_vector=embedding,
            sparse_vector=sparse_vec,
            filters=filters,
            top_k=fetch_k,
            prefetch_limit=fetch_k,
        )
    return qdrant.legacy_search(embedding, filters, fetch_k)


def _table_neighbor_expansion(points: list, qdrant: QdrantService, filters: dict) -> list:
    """Pull additional rows from same section/page as table hits."""
    if not settings.enable_retrieval_quality:
        return points
    sections: set[str] = set()
    pages: set[tuple] = set()
    for pt in points:
        p = pt.payload or {}
        if p.get("chunkType") == "coverage_table":
            if p.get("sectionId"):
                sections.add(p["sectionId"])
            pages.add((p.get("documentId"), p.get("pageNumber")))

    if not sections and not pages:
        return points

    try:
        all_pts, _ = qdrant.client.scroll(
            collection_name=qdrant.collection,
            scroll_filter=qdrant._build_filter(filters),
            limit=250,
            with_payload=True,
        )
    except Exception as exc:
        logger.warning("Table expansion scroll failed: %s", exc)
        return points

    existing = {id(pt) for pt in points}
    extra: list = []
    for pt in all_pts:
        if id(pt) in existing:
            continue
        p = pt.payload or {}
        if p.get("sectionId") in sections or (
            (p.get("documentId"), p.get("pageNumber")) in pages
            and p.get("chunkType") == "coverage_table"
        ):
            extra.append(
                wrap_scored_point(pt, float(getattr(pt, "score", 0) or 0) + 0.5)
            )

    if extra:
        logger.info("Table expansion added %d neighboring rows", len(extra))
    merged = list(points) + extra
    merged.sort(key=lambda p: float(getattr(p, "score", 0) or 0), reverse=True)
    return merged


def _merge_point_lists(primary: list, secondary: list) -> list:
    seen: set[int] = set()
    out: list = []
    for pt in primary + secondary:
        pid = id(pt)
        if pid in seen:
            continue
        seen.add(pid)
        out.append(pt)
    return out


def retrieve_with_pipeline(
    question: str,
    metadata: dict | None = None,
    top_k: int = 10,
    list_mode: bool | None = None,
    subqueries: list[str] | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    """
    Full retrieval pipeline. Returns (chunks for reasoning, debug trace).
    """
    trace: dict[str, Any] = {"steps": []}
    metadata = enrich_metadata_with_codes(metadata or {}, question)
    list_mode = is_list_or_filter_question(question) if list_mode is None else list_mode
    filters = qdrant_filters_from_metadata(metadata)
    qdrant = QdrantService()

    fetch_k = min(max(top_k * 5, 30), settings.retrieval_retry_top_k)
    if list_mode:
        fetch_k = max(fetch_k, 100)

    # Phase 3: coverage-code fast path
    codes = metadata.get("warranty_codes") or extract_warranty_codes(question)
    fast_hits: list = []
    if settings.enable_retrieval_quality and codes:
        fast_hits = _code_fast_path_lookup(qdrant, codes, filters, limit=fetch_k)
        trace["steps"].append({"fast_path_codes": codes, "hits": len(fast_hits)})

    queries = subqueries or [question]
    all_points: list = list(fast_hits)
    for qi, q in enumerate(queries):
        meta_q = enrich_metadata_with_codes(dict(metadata), q)
        pts = _hybrid_fetch(q, meta_q, filters, fetch_k, sparse_heavy=False)
        trace["steps"].append({"hybrid_query": q[:80], "hits": len(pts)})
        all_points = _merge_point_lists(all_points, pts)

    # Retry: sparse-heavy if too few points
    if settings.enable_retrieval_quality and len(all_points) < settings.retrieval_min_chunks:
        retry_pts = _hybrid_fetch(question, metadata, filters, fetch_k, sparse_heavy=True)
        trace["steps"].append({"retry_sparse_heavy": len(retry_pts)})
        all_points = _merge_point_lists(all_points, retry_pts)

    if settings.enable_retrieval_quality:
        all_points = _apply_score_threshold(all_points, settings.retrieval_score_threshold)
        all_points = _table_neighbor_expansion(all_points, qdrant, filters)

    all_points = rerank_with_lexical_boost(all_points, question, metadata)
    all_points = rerank_points(question, all_points, metadata, list_mode=list_mode)
    if list_mode:
        # Enumeration questions need every row of a coverage table, not top-k.
        all_points = dedupe_search_results(all_points, max(top_k, 40), max_per_doc_page=40)
    else:
        all_points = dedupe_search_results(all_points, top_k)

    chunks = [{"score": item.score, "payload": item.payload} for item in all_points]

    # Legacy structured meta backfill for old chunks
    for item in chunks:
        payload = item["payload"]
        if not payload.get("structuredMeta"):
            payload["structuredMeta"] = parse_chunk_structured_meta(payload)

    # Gate structured filtering: skip for simple coverage lookups ("is X covered?")
    # to let the reasoner evaluate date/mileage eligibility from evidence.
    if (settings.enable_structured_reasoning
            and is_structured_query(question)
            and not is_simple_retrieval_query(question)):
        constraints = parse_structured_constraints(question)
        filtered = apply_structured_filters(chunks, constraints)
        trace["structured_constraints"] = constraints
        trace["structured_kept"] = len(filtered)
        chunks = filtered

    chunks = expand_parents_for_reasoning(chunks)
    trace["final_chunks"] = len(chunks)

    logger.info(
        "Retrieval complete: %d chunks | filters=%s | question=%.80s",
        len(chunks), filters, question,
    )
    return chunks, trace
