import logging
import re

from ..config import settings
from ..services.query_decomposer import decompose_question, should_decompose
from ..services.retrieval_pipeline import retrieve_with_pipeline
from ..services.reranker_service import is_list_or_filter_question
from ..services.warranty_code_utils import enrich_metadata_with_codes, extract_warranty_codes

logger = logging.getLogger("retriever")

_CODE_IN_Q = re.compile(
    r"\b(U\d{2,4}[A-Z]?|D\d{3,4}|ET\d{2,4}|E\d{3,4}|G\d{2,3}|HAC\d{1,3}|TOW\d+|Z\d{3,4})\b",
    re.IGNORECASE,
)


def codes_in_question(question: str) -> list[str]:
    found = sorted({match.group(1).upper() for match in _CODE_IN_Q.finditer(question or "")})
    if found:
        return found
    return extract_warranty_codes(question)


def retrieve_chunks(
    question: str,
    metadata: dict | None = None,
    top_k: int = 10,
    list_mode: bool | None = None,
) -> list[dict]:
    """Hybrid retrieval with optional decomposition, quality gates, and parent expansion."""
    metadata = enrich_metadata_with_codes(metadata or {}, question)
    codes = codes_in_question(question)
    if codes:
        metadata["warranty_codes"] = list(
            dict.fromkeys((metadata.get("warranty_codes") or []) + codes)
        )
    list_mode = is_list_or_filter_question(question) if list_mode is None else list_mode

    subqueries = None
    if settings.enable_query_decomposition and should_decompose(question):
        subqueries = decompose_question(question, metadata)

    chunks, trace = retrieve_with_pipeline(
        question,
        metadata,
        top_k=top_k,
        list_mode=list_mode,
        subqueries=subqueries,
    )
    logger.info("Retrieval pipeline trace: %s", trace)

    # Enrich payload with chunk_id, section_heading, document_name (§3)
    for i, chunk in enumerate(chunks):
        p = chunk.get("payload") or {}
        if "chunk_id" not in p:
            p["chunk_id"] = (
                p.get("chunkId") or p.get("id")
                or f"{p.get('documentId', 'unknown')}-CHUNK-{i:04d}"
            )
        if "section_heading" not in p:
            p["section_heading"] = (
                p.get("sectionTitle") or p.get("sectionHeading")
                or p.get("coverageName") or None
            )
        if "document_name" not in p:
            p["document_name"] = p.get("filename") or p.get("documentName") or None

    return chunks
