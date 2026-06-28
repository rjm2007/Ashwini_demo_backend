"""Build parent-child chunk hierarchy for retrieval (child) + reasoning (parent)."""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict

from .coverage_row_parser import parse_coverage_row
from .strategic_chunker import _extract_coverage_rows, _extract_u_codes

logger = logging.getLogger("parent_child")


def _stable_id(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def build_parent_child_chunks(flat_chunks: list[dict], document_id: str) -> list[dict]:
    """
    Convert flat strategic chunks into searchable child chunks with parent context.

    - Table pages: one parent per page table section; one child per coverage row.
    - Other chunks: self-parent (parentChunkText = chunkText) for backward-compatible expansion.
    - Only children are returned for Qdrant upsert (chunkRole=child).
    """
    if not flat_chunks:
        return []

    by_page: dict[int, list[dict]] = defaultdict(list)
    for chunk in flat_chunks:
        by_page[int(chunk.get("pageNumber") or 1)].append(chunk)

    children: list[dict] = []
    chunk_idx = 0

    for page_num in sorted(by_page.keys()):
        page_chunks = by_page[page_num]
        table_chunks = [c for c in page_chunks if c.get("chunkType") == "coverage_table"]
        non_table = [c for c in page_chunks if c.get("chunkType") != "coverage_table"]

        if table_chunks:
            section_id = f"{document_id}-p{page_num}-coverage"
            section_title = table_chunks[0].get("sectionHeading") or "Coverage table"

            combined_rows: list[str] = []
            for tc in table_chunks:
                combined_rows.extend(_extract_coverage_rows(tc.get("chunkText") or ""))
            # dedupe rows preserving order
            seen_rows: set[str] = set()
            unique_rows: list[str] = []
            for row in combined_rows:
                key = row.strip()[:200]
                if key and key not in seen_rows:
                    seen_rows.add(key)
                    unique_rows.append(row.strip())

            vehicle_prefix = ""
            sample = table_chunks[0].get("chunkText") or ""
            if "[Vehicle context]" in sample:
                vehicle_prefix = sample.split("\n\n", 1)[0] + "\n\n"

            parent_text = vehicle_prefix + "\n".join(unique_rows) if unique_rows else sample
            parent_chunk_id = _stable_id(document_id, section_id, "parent")
            child_ids: list[str] = []

            for row in unique_rows or [parent_text]:
                codes = _extract_u_codes(row)
                child_chunk_id = _stable_id(document_id, section_id, "row", row[:120])
                child_ids.append(child_chunk_id)
                row_text = f"{vehicle_prefix}{row}".strip() if vehicle_prefix else row
                structured = parse_coverage_row(row, codes)

                child = {
                    **table_chunks[0],
                    "chunkIndex": chunk_idx,
                    "chunkText": row_text,
                    "chunkType": "coverage_table",
                    "coverageCodes": codes,
                    "chunkRole": "child",
                    "childChunkId": child_chunk_id,
                    "parentChunkId": parent_chunk_id,
                    "parentChunkText": parent_text,
                    "sectionId": section_id,
                    "sectionTitle": section_title,
                    "childChunkIds": [],
                    "structuredMeta": structured,
                }
                children.append(child)
                chunk_idx += 1

            for child in children:
                child["childChunkIds"] = child_ids

            logger.info(
                "Parent-child table page=%s parent=%s rows=%d",
                page_num,
                parent_chunk_id,
                len(unique_rows or [parent_text]),
            )

        for chunk in non_table:
            child_chunk_id = _stable_id(
                document_id,
                str(page_num),
                chunk.get("chunkType", "prose"),
                str(chunk.get("chunkIndex", chunk_idx)),
            )
            text = chunk.get("chunkText") or ""
            structured = chunk.get("structuredMeta") or parse_coverage_row(text, chunk.get("coverageCodes"))
            section_id = f"{document_id}-p{page_num}-{chunk.get('chunkType', 'section')}"
            children.append(
                {
                    **chunk,
                    "chunkIndex": chunk_idx,
                    "chunkRole": "child",
                    "childChunkId": child_chunk_id,
                    "parentChunkId": child_chunk_id,
                    "parentChunkText": text,
                    "sectionId": section_id,
                    "sectionTitle": chunk.get("sectionHeading") or chunk.get("chunkType"),
                    "childChunkIds": [child_chunk_id],
                    "structuredMeta": structured,
                }
            )
            chunk_idx += 1

    logger.info(
        "Parent-child built documentId=%s flat=%d searchable_children=%d",
        document_id,
        len(flat_chunks),
        len(children),
    )
    return children
