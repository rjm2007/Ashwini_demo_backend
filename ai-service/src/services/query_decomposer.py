"""Lightweight query decomposition for hard multi-condition questions only."""

from __future__ import annotations

import logging
import re

from .structured_query_engine import is_simple_retrieval_query, is_structured_query

logger = logging.getLogger("query_decomposer")

_HARD_RE = re.compile(
    r"\b(and|both|all .+ that|remain active|still apply|invalid|"
    r"combination|overlap|compare all|ordered by)\b",
    re.IGNORECASE,
)


def should_decompose(question: str) -> bool:
    if is_simple_retrieval_query(question):
        return False
    if not is_structured_query(question):
        return False
    q = question or ""
    if _HARD_RE.search(q):
        return True
    # multiple numeric constraints
    nums = re.findall(r"\d{2,}", q)
    return len(nums) >= 2 and len(q.split()) > 14


def decompose_question(question: str, metadata: dict | None = None) -> list[str]:
    """
    Split into focused subqueries for retrieval. Returns [original] if no split.
    """
    if not should_decompose(question):
        return [question]

    metadata = metadata or {}
    subs: list[str] = [question]
    codes = metadata.get("warranty_codes") or []
    for code in codes[:3]:
        subs.append(f"Coverage details for warranty code {code}")

    topics: list[str] = []
    q_lower = question.lower()
    if "drivetrain" in q_lower or "driveline" in q_lower or "transmission" in q_lower:
        topics.append("List drivetrain and transmission related warranty coverage rows")
    if "engine" in q_lower or "epa" in q_lower:
        topics.append("List engine and emission related warranty coverage rows")
    if "mile" in q_lower:
        topics.append("Warranty coverage rows with months and miles limits")
    if "year" in q_lower or "month" in q_lower:
        topics.append("Warranty duration months and expiration dates")

    for t in topics[:2]:
        if t not in subs:
            subs.append(t)

    logger.info("Decomposed question into %d subqueries", len(subs))
    return subs[:4]
