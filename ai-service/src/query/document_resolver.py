"""Resolve certified documents by make/model/year from applicability JSONB."""

from __future__ import annotations

import logging

from sqlalchemy import text

from ..database import SessionLocal

logger = logging.getLogger(__name__)


def resolve_documents_by_make_model_year(
    make: str | None,
    model: str | None,
    year: int | None = None,
    document_id: str | None = None,
) -> list[dict]:
    """Return certified document rows with master_schema_json."""
    if document_id:
        with SessionLocal() as session:
            row = session.execute(
                text(
                    "SELECT id, make, model, year, master_schema_json, document_type "
                    "FROM documents WHERE id = :id AND current_repository = 'certified'"
                ),
                {"id": document_id},
            ).first()
        if not row:
            return []
        schema = row[4] if isinstance(row[4], dict) else {}
        return [
            {
                "documentId": str(row[0]),
                "make": row[1],
                "model": row[2],
                "year": row[3],
                "document_type": row[5],
                "master_schema": schema,
            }
        ]

    if not make:
        return []

    make_pat = f"%{make.strip()}%"
    clauses = [
        "current_repository = 'certified'",
        "("
        "master_schema_json -> 'applicability' ->> 'make' ILIKE :make_pat "
        "OR make ILIKE :make_pat"
        ")",
    ]
    params: dict = {"make_pat": make_pat}
    if model:
        model_pat = f"%{model.strip()}%"
        clauses.append(
            "("
            "model ILIKE :model_pat "
            "OR master_schema_json -> 'asset_context' ->> 'model' ILIKE :model_pat "
            "OR EXISTS ("
            "  SELECT 1 FROM jsonb_array_elements_text("
            "    COALESCE(master_schema_json -> 'applicability' -> 'models', '[]'::jsonb)"
            "  ) AS m(val) WHERE m.val ILIKE :model_pat"
            ")"
            ")"
        )
        params["model_pat"] = model_pat
    if year:
        clauses.append(
            "("
            "year = :year "
            "OR master_schema_json -> 'applicability' -> 'model_years' @> :year_json "
            "OR ("
            "  COALESCE(jsonb_array_length("
            "    master_schema_json -> 'applicability' -> 'model_years' -> 'specific_years'"
            "  ), 0) = 0 "
            "  AND (master_schema_json -> 'applicability' -> 'model_years' ->> 'from') IS NULL"
            ")"
            ")"
        )
        params["year"] = year
        params["year_json"] = f'{{"specific_years": [{year}]}}'

    sql = (
        "SELECT id, make, model, year, master_schema_json, document_type FROM documents "
        f"WHERE {' AND '.join(clauses)} ORDER BY uploaded_at DESC LIMIT 5"
    )
    with SessionLocal() as session:
        rows = session.execute(text(sql), params).fetchall()

    out: list[dict] = []
    for row in rows:
        schema = row[4] if isinstance(row[4], dict) else {}
        out.append(
            {
                "documentId": str(row[0]),
                "make": row[1],
                "model": row[2],
                "year": row[3],
                "document_type": row[5],
                "master_schema": schema,
            }
        )
    return out
