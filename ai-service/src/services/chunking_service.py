"""Warranty-aware chunking (strategic tiktoken). Replaces legacy word-based splitting."""

from ..config import settings
from .parent_child_builder import build_parent_child_chunks
from .strategic_chunker import TiktokenChunker

_chunker = TiktokenChunker()


def chunk_pages_flat(pages: list[dict]) -> list[dict]:
    """Chunk OCR pages without parent-child wrapping."""
    return _chunker.chunk_pages(pages)


def chunk_pages(pages: list[dict], document_id: str | None = None) -> list[dict]:
    """Chunk OCR pages with layout-aware strategy (tables, policy sections, prose)."""
    flat = chunk_pages_flat(pages)
    if settings.enable_parent_child and document_id:
        return build_parent_child_chunks(flat, document_id)
    return flat


def chunk_text(text: str) -> list[dict]:
    """Fallback when only a single text blob is available."""
    if not (text or "").strip():
        return []
    return _chunker.chunk_pages([{"page": 1, "text": text}])
