"""
summary_generator.py

Generates a human-readable executive summary of the document
using the large model (one call) after master schema is built.

Output stored in documents.ai_summary_text.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy import text

from ..config import settings
from ..database import SessionLocal
from ..services.llm_service import LlmService

logger = logging.getLogger("summary_generator")

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "generate_summary.txt"


def generate_document_summary(document_id: str, master_schema: dict) -> str:
    """
    Call the large model to produce a natural language summary.
    Writes result to documents.ai_summary_text.
    Returns the summary string.
    """
    llm = LlmService()

    # Build a compact, readable version of the schema for the prompt
    # (exclude raw field wrappers — just key:value pairs)
    compact = _schema_to_compact(master_schema)
    prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")

    prompt = f"{prompt_template}\n\n<DOCUMENT_DATA>\n{compact}\n</DOCUMENT_DATA>"

    summary = llm.large_model_call(
        prompt=prompt,
        system_message="Generate a concise, professional document summary. Plain prose only.",
    )
    summary = summary.strip()

    with SessionLocal() as session:
        session.execute(
            text("UPDATE documents SET ai_summary_text = :s, updated_at = NOW() WHERE id = :id"),
            {"s": summary, "id": document_id},
        )
        session.commit()

    logger.info("[%s] Summary generated: %d chars", document_id, len(summary))
    return summary


def _schema_to_compact(schema: dict) -> str:
    """Convert master_schema field wrappers to a flat key:value text block."""
    lines = []

    def _extract(obj, prefix=""):
        if isinstance(obj, dict):
            if "value" in obj and "status" in obj:
                val = obj.get("value")
                st = obj.get("status", "")
                if val is not None and st != "missing":
                    lines.append(f"{prefix}: {val}")
            else:
                for k, v in obj.items():
                    if k in ("quality", "extensions", "document_tree"):
                        continue
                    _extract(v, f"{prefix}.{k}" if prefix else k)
        elif isinstance(obj, list):
            for i, item in enumerate(obj[:20]):  # cap at 20 items
                _extract(item, f"{prefix}[{i}]")

    _extract(schema)
    return "\n".join(lines)
