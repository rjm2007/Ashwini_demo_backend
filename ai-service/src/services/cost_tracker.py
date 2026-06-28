"""Per-call LLM/OCR/embedding cost tracking."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from pydantic import BaseModel

from sqlalchemy import text

from ..database import SessionLocal
from .pricing import estimate_cost_usd
from ..config import settings

logger = logging.getLogger("cost_tracker")

class RequestUsage(BaseModel):
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_usd: float = 0.0
    calls: int = 0
    
_REQUEST_USAGE: ContextVar[RequestUsage | None] = ContextVar("_REQUEST_USAGE", default=None)

def start_request() -> None:
    _REQUEST_USAGE.set(RequestUsage())

def request_cost_summary() -> dict | None:
    usage = _REQUEST_USAGE.get()
    if not usage:
        return None
    return {
        "prompt_tokens": usage.total_prompt_tokens,
        "completion_tokens": usage.total_completion_tokens,
        "total_tokens": usage.total_prompt_tokens + usage.total_completion_tokens,
        "usd": round(usage.total_usd, 5),
        "calls": usage.calls
    }


def record_cost(
    *,
    stage: str,
    provider: str,
    model: str,
    document_id: str | None = None,
    session_id: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    units: float | None = None,
    unit_kind: str | None = None,
) -> float:
    usd = estimate_cost_usd(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        units=units,
        unit_kind=unit_kind,
    )

    # Accumulate into contextvar if active (and it's OpenAI to match LLM_PRICE_TABLE)
    usage = _REQUEST_USAGE.get()
    if usage and provider == "openai":
        p_tokens = input_tokens or 0
        c_tokens = output_tokens or 0
        usage.total_prompt_tokens += p_tokens
        usage.total_completion_tokens += c_tokens
        usage.calls += 1
        
        rates = settings.LLM_PRICE_TABLE.get(model)
        if rates:
            usage.total_usd += (p_tokens / 1_000_000) * rates["prompt"]
            usage.total_usd += (c_tokens / 1_000_000) * rates["completion"]
        else:
            usage.total_usd += usd
    try:
        with SessionLocal() as session:
            session.execute(
                text(
                    """
                    INSERT INTO cost_events
                      (document_id, session_id, stage, provider, model,
                       input_tokens, output_tokens, units, unit_kind, usd_cost)
                    VALUES
                      (:document_id, :session_id, :stage, :provider, :model,
                       :input_tokens, :output_tokens, :units, :unit_kind, :usd_cost)
                    """
                ),
                {
                    "document_id": document_id,
                    "session_id": session_id,
                    "stage": stage,
                    "provider": provider,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "units": units,
                    "unit_kind": unit_kind,
                    "usd_cost": usd,
                },
            )
            session.commit()
    except Exception as exc:
        logger.warning("cost_events insert failed: %s", exc)
    return usd


def sum_document_cost(document_id: str) -> float:
    with SessionLocal() as session:
        row = session.execute(
            text("SELECT COALESCE(SUM(usd_cost), 0) FROM cost_events WHERE document_id = :id"),
            {"id": document_id},
        ).first()
    return float(row[0] if row else 0)


def sum_session_cost(session_id: str) -> float:
    with SessionLocal() as session:
        row = session.execute(
            text("SELECT COALESCE(SUM(usd_cost), 0) FROM cost_events WHERE session_id = :id"),
            {"id": session_id},
        ).first()
    return float(row[0] if row else 0)
