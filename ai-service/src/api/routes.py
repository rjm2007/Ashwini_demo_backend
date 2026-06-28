import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from ..database import SessionLocal
from ..query.query_orchestrator import answer_question
from ..query.defect_workflow import answer_defect_thread
from ..services.qdrant_service import QdrantService
from ..workers.pipeline_orchestrator import run_act1_parse, run_act2_process
from ..services.cost_tracker import record_cost, sum_document_cost, sum_session_cost

logger = logging.getLogger(__name__)

router = APIRouter()


class QueryRequest(BaseModel):
    question: str
    conversationHistory: list[dict[str, Any]] = []
    documentId: str | None = None
    sessionId: str | None = None
    context: dict[str, Any] | None = None

class DefectAnswerRequest(BaseModel):
    question: str
    documentId: str
    context: dict[str, Any] | None = None
    conversationHistory: list[dict[str, Any]] = []


class SetRepositoryRequest(BaseModel):
    repository: str


ALLOWED_REPOSITORIES = {"pending_review", "reviewer_approved", "certified", "rejected"}


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/internal/parse/{document_id}")
async def trigger_parse(document_id: str) -> dict:
    asyncio.create_task(run_act1_parse(document_id))
    return {"status": "started", "act": 1, "documentId": document_id}


@router.post("/internal/process/{document_id}")
async def trigger_process(document_id: str) -> dict:
    asyncio.create_task(run_act2_process(document_id))
    return {"status": "started", "act": 2, "documentId": document_id}


@router.get("/internal/summary/{document_id}")
async def get_summary(document_id: str) -> dict:
    """Return WARR-1172-shaped master schema with stats rollup."""
    with SessionLocal() as session:
        row = session.execute(
            text("SELECT master_schema_json, original_filename FROM documents WHERE id = :id"),
            {"id": document_id},
        ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    schema = row[0] if isinstance(row[0], dict) else {}
    filename = row[1] or ""
    return build_summary_response(schema, document_id, filename)


@router.get("/cost/document/{document_id}")
async def get_document_cost(document_id: str) -> dict:
    total = sum_document_cost(document_id)
    with SessionLocal() as session:
        rows = session.execute(
            text(
                "SELECT stage, provider, model, SUM(usd_cost) AS usd, COUNT(*) AS calls "
                "FROM cost_events WHERE document_id = :id GROUP BY stage, provider, model "
                "ORDER BY usd DESC"
            ),
            {"id": document_id},
        ).fetchall()
    return {
        "documentId": document_id,
        "totalUsd": total,
        "breakdown": [
            {"stage": r[0], "provider": r[1], "model": r[2], "usd": float(r[3]), "calls": r[4]}
            for r in rows
        ],
    }


@router.get("/cost/session/{session_id}")
async def get_session_cost(session_id: str) -> dict:
    return {"sessionId": session_id, "totalUsd": sum_session_cost(session_id)}


@router.get("/cost/daily")
async def get_daily_cost() -> dict:
    with SessionLocal() as session:
        row = session.execute(
            text(
                "SELECT COALESCE(SUM(usd_cost), 0) FROM cost_events "
                "WHERE created_at >= date_trunc('day', NOW())"
            )
        ).first()
        rows = session.execute(
            text(
                "SELECT stage, SUM(usd_cost) FROM cost_events "
                "WHERE created_at >= date_trunc('day', NOW()) GROUP BY stage"
            )
        ).fetchall()
    return {
        "totalUsd": float(row[0] if row else 0),
        "byStage": {r[0]: float(r[1]) for r in rows},
    }


@router.post("/query/answer")
async def query_answer(payload: QueryRequest) -> dict[str, Any]:
    from ..services.cost_tracker import start_request, request_cost_summary
    start_request()
    ans = await answer_question(
        payload.question,
        payload.conversationHistory,
        payload.documentId,
        context=payload.context,
        session_id=payload.sessionId,
    )
    ans["cost"] = request_cost_summary()
    return ans


@router.post("/defect/answer")
async def defect_answer(payload: DefectAnswerRequest) -> dict[str, Any]:
    from ..services.cost_tracker import start_request, request_cost_summary
    start_request()
    ans = answer_defect_thread(
        question=payload.question,
        document_id=payload.documentId,
        context=payload.context,
        conversation_history=payload.conversationHistory,
    )
    ans["cost"] = request_cost_summary()
    return ans


@router.post("/internal/set-repository/{document_id}")
async def set_repository(document_id: str, payload: SetRepositoryRequest) -> dict[str, Any]:
    if payload.repository not in ALLOWED_REPOSITORIES:
        raise HTTPException(
            status_code=400,
            detail=f"repository must be one of {sorted(ALLOWED_REPOSITORIES)}",
        )
    try:
        qdrant = QdrantService()
        updated = qdrant.update_repository(document_id, payload.repository)
        if updated == 0:
            raise HTTPException(
                status_code=404,
                detail=f"No chunks found in Qdrant for document {document_id}.",
            )
        return {
            "success": True,
            "documentId": document_id,
            "repository": payload.repository,
            "updatedChunks": updated,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/internal/update-chunks")
async def update_chunks(payload: dict[str, Any]) -> dict[str, Any]:
    return {"status": "not_implemented", "payload": payload}
