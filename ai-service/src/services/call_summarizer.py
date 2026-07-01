"""
call_summarizer.py

Turns a raw Vapi call transcript into the structured fields the Call Logs UI
needs (event description, summary, recommendation, documents collected /
pending). Called once, right after Vapi's end-of-call-report webhook lands
on the backend, which proxies the transcript here — same proxy pattern
already used for POST /voice/translate.
"""

import json
import logging
import re
from pathlib import Path

from .llm_service import LlmService

logger = logging.getLogger("call_summarizer")

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "call_summary.txt"


def _parse_json(raw: str) -> dict:
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return json.loads(s.strip())


def summarize_call(transcript: str, agent_key: str, agent_name: str = "") -> dict:
    """
    Returns:
    {
      "eventDescription": str,
      "summary": str,
      "recommendation": str,
      "documentsCollected": list[str],
      "documentsPending": list[str],
    }
    Falls back to a safe, honest default if the transcript is empty or the
    model output can't be parsed — never raises, since this must not block
    persisting the call log.
    """
    fallback = {
        "eventDescription": "Call logged",
        "summary": "No transcript was available to summarize for this call.",
        "recommendation": "Review the raw transcript manually.",
        "documentsCollected": [],
        "documentsPending": [],
    }

    text = (transcript or "").strip()
    if not text:
        return fallback

    llm = LlmService()
    prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (
        f"{prompt_template}\n\nAgent role: {agent_key} ({agent_name})\n\n"
        f"<TRANSCRIPT>\n{text[:20000]}\n</TRANSCRIPT>"
    )

    try:
        raw = llm.small_model_call(
            prompt=prompt,
            system_message="Return only the JSON object described. No markdown, no commentary.",
            stage="call_summary",
        )
        data = _parse_json(raw)
    except Exception as exc:
        logger.error("call_summarizer failed, using fallback: %s", exc, exc_info=True)
        return fallback

    return {
        "eventDescription": str(data.get("eventDescription") or fallback["eventDescription"])[:255],
        "summary": str(data.get("summary") or fallback["summary"]),
        "recommendation": str(data.get("recommendation") or fallback["recommendation"]),
        "documentsCollected": data.get("documentsCollected") if isinstance(data.get("documentsCollected"), list) else [],
        "documentsPending": data.get("documentsPending") if isinstance(data.get("documentsPending"), list) else [],
    }
