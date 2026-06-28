"""Dense embeddings + optional contextual retrieval for hybrid Qdrant upsert."""

import logging

from openai import OpenAI

from ..config import settings
from .contextual_retrieval import ContextualRetrieval
from .cost_tracker import record_cost
from .sparse_encoder import BM25SparseEncoder

logger = logging.getLogger("embedding")


def embed_texts(texts: list[str], document_id: str | None = None) -> list[list[float]]:
    if not texts:
        return []
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.embeddings.create(model="text-embedding-3-small", input=texts)
    usage = getattr(response, "usage", None)
    if usage:
        record_cost(
            stage="embedding",
            provider="openai",
            model="text-embedding-3-small",
            document_id=document_id,
            input_tokens=getattr(usage, "total_tokens", None) or getattr(usage, "prompt_tokens", None),
            output_tokens=0,
        )
    return [item.embedding for item in response.data]


def prepare_chunks_for_upsert(
    chunks: list[dict],
    full_doc_text: str,
    *,
    enable_contextual: bool = True,
    enable_sparse: bool = True,
    document_id: str | None = None,
) -> list[dict]:
    """
    Add contextualizedText (optional), dense vectors, and BM25 sparse vectors.
    """
    if not chunks:
        return []

    if enable_contextual:
        chunks = ContextualRetrieval().contextualize_chunks(full_doc_text, chunks, document_id=document_id)
    else:
        for chunk in chunks:
            chunk["contextualizedText"] = chunk["chunkText"]
            chunk["contextBlurb"] = ""

    texts = [c.get("contextualizedText") or c["chunkText"] for c in chunks]
    vectors = embed_texts(texts, document_id=document_id)

    sparse_enc = BM25SparseEncoder(vocab_size=settings.bm25_vocab_size) if enable_sparse else None

    for i, chunk in enumerate(chunks):
        chunk["vector"] = vectors[i] if i < len(vectors) else []
        if sparse_enc:
            chunk["sparse_vector"] = sparse_enc.encode(texts[i])
        chunk["hasContextBlurb"] = bool(chunk.get("contextBlurb"))
        chunk["chunkStrategy"] = "warranty_strategic_v2"

    logger.info("Prepared %d chunks for upsert (context=%s sparse=%s)", len(chunks), enable_contextual, enable_sparse)
    return chunks


def embed_chunks(chunks: list[str]) -> list[list[float]]:
    """Legacy helper — embed raw strings only."""
    return embed_texts(chunks)
