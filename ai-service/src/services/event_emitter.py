"""Writes pipeline_events rows to Postgres during pipeline execution."""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field

from sqlalchemy import text

from ..database import SessionLocal

logger = logging.getLogger("event_emitter")


@dataclass
class StepHandle:
    document_id: str
    event_id: str
    act: int
    stage: str
    step_key: str
    step_label: str
    sequence: int
    start_time: float = field(default_factory=time.monotonic)


def _next_sequence(session, document_id: str) -> int:
    result = session.execute(
        text("SELECT COALESCE(MAX(sequence), 0) + 1 FROM pipeline_events WHERE document_id = :id"),
        {"id": document_id},
    ).scalar()
    return int(result or 1)


def start_step(document_id: str, act: int, stage: str, step_key: str, step_label: str) -> StepHandle:
    event_id = str(uuid.uuid4())
    with SessionLocal() as session:
        seq = _next_sequence(session, document_id)
        session.execute(
            text("""
                INSERT INTO pipeline_events
                  (id, document_id, act, stage, step_key, step_label, status, sequence)
                VALUES
                  (:id, :doc, :act, :stage, :step_key, :label, 'running', :seq)
            """),
            {
                "id": event_id,
                "doc": document_id,
                "act": act,
                "stage": stage,
                "step_key": step_key,
                "label": step_label,
                "seq": seq,
            },
        )
        session.commit()
    logger.info("[%s] ACT%s STEP_START %s — %s", document_id, act, step_key, step_label)
    return StepHandle(
        document_id=document_id,
        event_id=event_id,
        act=act,
        stage=stage,
        step_key=step_key,
        step_label=step_label,
        sequence=seq,
    )


def finish_step(handle: StepHandle, detail: dict | None = None, status: str = "done") -> None:
    duration_ms = int((time.monotonic() - handle.start_time) * 1000)
    detail = detail or {}
    with SessionLocal() as session:
        session.execute(
            text("""
                UPDATE pipeline_events
                SET status = :status, detail = CAST(:detail AS jsonb), duration_ms = :dur
                WHERE id = :id
            """),
            {"status": status, "detail": json.dumps(detail), "dur": duration_ms, "id": handle.event_id},
        )
        session.commit()
    logger.info(
        "[%s] ACT%s STEP_%s %s — %dms %s",
        handle.document_id,
        handle.act,
        status.upper(),
        handle.step_key,
        duration_ms,
        detail,
    )


@contextmanager
def pipeline_step(document_id: str, act: int, stage: str, step_key: str, step_label: str):
    handle = start_step(document_id, act, stage, step_key, step_label)
    detail: dict = {}
    try:
        yield detail
        finish_step(handle, detail=detail, status="done")
    except Exception as exc:
        finish_step(handle, detail={"error": str(exc)[:500]}, status="failed")
        raise
