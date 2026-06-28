"""Classify sections and detect document_type using the small LLM."""

from __future__ import annotations

import json
import logging
import re as _re
from pathlib import Path

from sqlalchemy import text

from ..database import SessionLocal
from ..services.llm_service import LlmService

logger = logging.getLogger("section_classifier")
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "section_classification.txt"


def _parse_llm_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = _re.sub(r"^```(?:json)?\s*", "", text)
        text = _re.sub(r"\s*```$", "", text)
    return json.loads(text.strip())


def _index_from_ref(ref: str | None) -> int | None:
    """'#/texts/12' → 12. Returns None if no match."""
    if not isinstance(ref, str):
        return None
    m = _re.search(r"/texts/(\d+)", ref)
    return int(m.group(1)) if m else None


def classify_sections(
    document_id: str,
    document_tree: list[dict],
    headings: list[dict],
    tables: list[dict],
    md_content: str,
    plain_text: str,
) -> dict:
    llm = LlmService()
    prompt = _PROMPT_PATH.read_text(encoding="utf-8")

    # Build classifier input — headings have `index`, hierarchy doesn't
    heading_lines = "\n".join(
        f"[idx={h.get('index')}] [p{h.get('page')}] {h.get('label', '')}: {h.get('text_preview', '')}"
        for h in headings[:40]
    )
    table_lines = "\n".join(
        f"[p{t.get('page')}] Table #{t.get('index')}: {t.get('cell_count')} cells"
        for t in tables[:10]
    )
    text_sample = (md_content or plain_text)[:3000]

    context = (
        f"HEADINGS_AND_SECTIONS:\n{heading_lines}\n\n"
        f"TABLES:\n{table_lines}\n\n"
        f"DOCUMENT_TEXT_SAMPLE:\n{text_sample}"
    )
    raw = llm.small_model_call(
        prompt=f"{prompt}\n\n<DOCUMENT_CONTEXT>\n{context}\n</DOCUMENT_CONTEXT>",
        system_message="Classify document sections. Return JSON only.",
    )

    try:
        result = _parse_llm_json(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("[%s] Section classifier JSON parse failed", document_id)
        result = {"document_type": "generic_document", "section_labels": []}

    document_type = result.get("document_type", "generic_document")
    section_labels = result.get("section_labels", [])

    # Build a label map keyed by integer index
    label_map: dict[int, str] = {}
    for item in section_labels:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        lbl = item.get("label")
        if isinstance(idx, int) and isinstance(lbl, str):
            label_map[idx] = lbl

    # ── Enrich hierarchy by deriving index from ref ──
    enriched_tree = []
    for node in document_tree:
        idx = _index_from_ref(node.get("ref"))
        enriched_tree.append({
            **node,
            "index": idx,
            "section_label": label_map.get(idx, "other"),
        })

    # ── Enrich headings/sections — these ALREADY have `index` ──
    # This is what schema extraction will actually use.
    enriched_sections = []
    for h in headings:
        idx = h.get("index")
        enriched_sections.append({
            **h,
            "section_label": label_map.get(idx, "other") if isinstance(idx, int) else "other",
        })

    # Write BOTH to documents
    with SessionLocal() as session:
        session.execute(
            text("""
                UPDATE documents
                SET document_type          = :dtype,
                    document_tree_json     = CAST(:tree AS jsonb),
                    document_sections_json = CAST(:sections AS jsonb),
                    updated_at = NOW()
                WHERE id = :id
            """),
            {
                "dtype": document_type,
                "tree": json.dumps(enriched_tree),
                "sections": json.dumps(enriched_sections),
                "id": document_id,
            },
        )
        session.commit()

    logger.info(
        "[%s] document_type=%s sections_labeled=%d (mapped %d via label_map)",
        document_id, document_type, len(section_labels), len(label_map),
    )
    return {
        "document_type": document_type,
        "section_labels": section_labels,
        "enriched_sections": enriched_sections,
        "enriched_tree": enriched_tree,
    }
