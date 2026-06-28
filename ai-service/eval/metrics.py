"""Retrieval evaluation metrics for benchmark harness."""

from __future__ import annotations


def recall_at_k(required: list[str], blob: str, k: int) -> float:
    if not required:
        return 1.0
    hits = sum(1 for token in required if token.upper() in blob.upper())
    return hits / len(required)


def precision_at_k(required: list[str], blob: str, k: int) -> float:
    """Proxy: fraction of required tokens found in top-k blob."""
    return recall_at_k(required, blob, k)


def mrr(required: list[str], chunk_blobs: list[str]) -> float:
    """Mean reciprocal rank of first chunk containing any required token."""
    if not required:
        return 1.0
    for rank, blob in enumerate(chunk_blobs, start=1):
        if any(t.upper() in blob.upper() for t in required):
            return 1.0 / rank
    return 0.0
