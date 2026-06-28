import json
import logging
from pathlib import Path

from ..services.llm_service import LlmService

logger = logging.getLogger("intent_classifier")

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

_DEFAULT = {
    "intent": "warranty_coverage",
    "confidence": 0.5,
    "requires_retrieval": True,
    "needs_clarification": False,
    "clarification_question": None,
    "abuse_signal": False,
    "scope_reason": "",
    "language": "en",
}


def classify_intent(
    question: str,
    conversation_history: list[dict] | None = None,
    *,
    document_id: str | None = None,
    doc_context: dict | None = None,
) -> dict:
    """Classify user intent and routing hints (small model)."""
    llm = LlmService()
    prompt = (_PROMPTS_DIR / "intent_classification.txt").read_text(encoding="utf-8")

    history_block = ""
    if conversation_history:
        lines = [
            f"{item.get('role', 'user')}: {item.get('content', '')}"
            for item in conversation_history[-6:]
        ]
        history_block = "\nCONVERSATION HISTORY:\n" + "\n".join(lines)

    # When a specific document is pinned, tell the classifier not to bounce
    # broad/document-level questions as "ambiguous".
    scope_block = ""
    if document_id:
        ctx = doc_context or {}
        ctx_str = ", ".join(f"{k}={v}" for k, v in ctx.items() if v) or "certified document"
        scope_block = (
            "\n\nDOCUMENT IN SCOPE: A single certified document is already selected by the user.\n"
            f"Known context for this document: {ctx_str}\n"
            "Because the document is fixed, do NOT return intent=\"ambiguous\" for a missing "
            "vehicle/component/VIN. Treat document-level questions (\"what does this cover\", "
            "\"summarize this\", \"what's excluded\", \"what is the warranty period\", \"what does "
            "this warranty cover\") as intent=\"warranty_coverage\" with requires_retrieval=true.\n"
            "Only return \"ambiguous\" if the question is genuinely uninterpretable even with the "
            "document in scope.\n"
        )

    output = llm.small_model_call(
        f"{prompt}{history_block}{scope_block}\n\nUSER QUESTION: {question}",
        "Classify intent. Return JSON only.",
    )
    try:
        payload = json.loads(output)
        if isinstance(payload, dict):
            merged = {**_DEFAULT, **payload}
            return merged
    except json.JSONDecodeError:
        logger.warning("Intent JSON parse failed, defaulting to warranty_coverage")

    lowered = (question or "").strip().lower()
    if lowered in {"hi", "hello", "hey", "hola", "good morning", "good afternoon", "good evening"}:
        return {
            **_DEFAULT,
            "intent": "greeting_or_smalltalk",
            "confidence": 0.95,
            "requires_retrieval": False,
            "scope_reason": "Short greeting detected via fallback.",
        }

    return dict(_DEFAULT)
