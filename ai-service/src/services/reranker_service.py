"""Phase 2 — rerank hybrid candidates before dedupe and reasoning."""

from __future__ import annotations

import json
import logging
import re

from ..config import settings
from .llm_service import LlmService
from .retrieval_utils import lexical_match_bonus

logger = logging.getLogger("reranker")

_LIST_QUERY_RE = re.compile(
    r"\b("
    r"list|show all|which warranties|which coverages|find all|"
    r"expire|expir|related to|all warranties|all coverages|"
    r"how many warranties|compare all|drivetrain-related"
    r")\b",
    re.IGNORECASE,
)


def is_list_or_filter_question(question: str) -> bool:
    """Detect list/filter/compare-many queries → table reasoning mode."""
    q = (question or "").lower()
    if _LIST_QUERY_RE.search(q):
        return True
    if re.search(r"\bwhich\b.+\b(have|are|mention|provide|exceed|remain)\b", q):
        return True
    if re.search(r"\b(greater|longer|shorter|highest|lowest|average)\b", q):
        return True
    return False


def _chunk_snippet(payload: dict, max_chars: int = 420) -> str:
    text = payload.get("chunkText") or ""
    codes = payload.get("coverageCodes") or []
    prefix = ""
    if codes:
        prefix = f"codes={','.join(str(c) for c in codes[:6])} | "
    return prefix + text[:max_chars]


def boost_table_chunks(points: list, list_mode: bool) -> list:
    """Prefer coverage_table chunks for list/filter questions."""
    if not list_mode:
        return points
    scored: list[tuple[float, object]] = []
    for point in points:
        base = float(getattr(point, "score", 0) or 0)
        payload = point.payload or {}
        if payload.get("chunkType") == "coverage_table":
            base += 2.0
        try:
            point.score = base
        except (AttributeError, TypeError):
            pass
        scored.append((base, point))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored]


def rerank_points(
    question: str,
    points: list,
    metadata: dict | None = None,
    list_mode: bool = False,
) -> list:
    """
    Rerank Qdrant hits: table boost → optional OpenAI cross-rerank → lexical tie-break.
  """
    if not points:
        return points

    metadata = metadata or {}
    points = boost_table_chunks(points, list_mode)

    if (
        not settings.enable_reranker
        or settings.reranker_provider == "none"
        or len(points) <= 1
    ):
        return points

    candidates = points[: settings.reranker_candidates]
    tail = points[settings.reranker_candidates :]

    try:
        ordered = _openai_rerank(question, candidates, metadata)
        return ordered + tail
    except Exception as exc:
        logger.warning("OpenAI rerank failed, keeping lexical order: %s", exc)
        return points


def _openai_rerank(question: str, points: list, metadata: dict) -> list:
    """Small-model relevance ordering for top-N chunks."""
    lines = []
    for idx, point in enumerate(points, start=1):
        payload = point.payload or {}
        page = payload.get("pageNumber", "?")
        ctype = payload.get("chunkType", "?")
        lines.append(
            f"[{idx}] page={page} type={ctype}\n{_chunk_snippet(payload)}"
        )

    codes = metadata.get("warranty_codes") or []
    code_hint = f" Target codes/keywords: {', '.join(codes)}." if codes else ""

    prompt = (
        f"QUESTION: {question}{code_hint}\n\n"
        f"CHUNKS (numbered 1..{len(points)}):\n\n"
        + "\n\n".join(lines)
        + "\n\nReturn JSON only: {\"order\": [most relevant index first, ...]} "
        f"using each index 1..{len(points)} exactly once."
    )

    llm = LlmService()
    raw = llm.small_model_call(
        prompt,
        "You rank warranty document chunks by relevance to the question. JSON only.",
    )
    payload = json.loads(raw)
    order = payload.get("order") or payload.get("ranking") or []
    if not isinstance(order, list) or not order:
        return points

    index_map = {i + 1: points[i] for i in range(len(points))}
    seen: set[int] = set()
    reranked: list = []
    for item in order:
        try:
            n = int(item)
        except (TypeError, ValueError):
            continue
        if n in index_map and n not in seen:
            seen.add(n)
            pt = index_map[n]
            bonus = lexical_match_bonus(
                pt.payload or {},
                metadata.get("warranty_codes") or [],
                metadata.get("semantic_keywords") or [],
            )
            try:
                pt.score = float(len(points) - len(reranked)) + bonus * 0.1
            except (AttributeError, TypeError):
                pass
            reranked.append(pt)

    for i, pt in enumerate(points, start=1):
        if i not in seen:
            reranked.append(pt)

    logger.info("OpenAI rerank reordered %d chunks", len(reranked))
    return reranked
