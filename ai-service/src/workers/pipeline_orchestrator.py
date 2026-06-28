"""Two-act pipeline: Act 1 on upload, Act 2 on certify."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import text

from ..config import settings
from ..database import SessionLocal
from ..services.chunking_service import chunk_pages, chunk_pages_flat, chunk_text
from ..services.coverage_row_parser import parse_chunk_structured_meta
from ..services.docling_structure_service import check_health, parse_structured
from ..services.embedding_service import prepare_chunks_for_upsert
from ..services.event_emitter import finish_step, start_step
from ..services.ocr_service import OcrService
from ..services.cost_tracker import record_cost
from ..services.parent_child_builder import build_parent_child_chunks
from ..services.qdrant_service import QdrantService
from ..services.warranty_chunk_builder import build_warranty_chunks, has_usable_warranty_schema
from ..services.schema_chunk_builder import build_schema_chunks, has_usable_schema
from ..services.section_classifier import classify_sections
from ..services.s3_service import S3Service
from ..services.strategic_chunker import parse_vin_chassis_from_text
from ..services.vehicle_fallback_service import run_vehicle_fallback

logger = logging.getLogger("pipeline")
logger.setLevel(logging.INFO)


async def _update_status(document_id: str, status: str, error: str | None = None) -> None:
    with SessionLocal() as session:
        session.execute(
            text("""
                UPDATE documents
                SET processing_status = CAST(:status AS processing_status),
                    error_message = :err,
                    updated_at = NOW()
                WHERE id = :id
            """),
            {"status": status, "err": error, "id": document_id},
        )
        session.commit()


async def run_act1_parse(document_id: str, s3_path: str | None = None) -> None:
    """ACT 1: parse → tree → classify → awaiting_certification (no embeddings)."""
    from ..services.cost_tracker import start_request, request_cost_summary
    start_request()
    logger.info("[%s] ACT 1 START", document_id)
    s3 = S3Service()

    if not s3_path:
        with SessionLocal() as session:
            row = session.execute(
                text("SELECT s3_path FROM documents WHERE id = :id"),
                {"id": document_id},
            ).first()
            s3_path = row[0] if row else None
    if not s3_path:
        logger.error("[%s] ACT 1 ABORT: no s3_path", document_id)
        return

    try:
        step = start_step(document_id, 1, "parse", "pdf_received", "PDF received")
        finish_step(step, {"s3_path": s3_path})
        await _update_status(document_id, "parsing")

        step = start_step(document_id, 1, "parse", "docling_parse", "Parsing document (Docling)")
        structured: dict
        try:
            pdf_bytes = await s3.download_bytes(s3_path)
            if settings.parser_primary in ("docling_structured", "auto") and check_health().get("ok"):
                structured = parse_structured(pdf_bytes)
            else:
                raise RuntimeError("Docling structured parser unavailable")
            await s3.upload_json(f"processing-artifacts/{document_id}/structure.json", structured)
            finish_step(
                step,
                {
                    "pages": len(structured.get("pages_text", [])),
                    "tables": structured.get("table_count", 0),
                    "headings": len(structured.get("headings", [])),
                    "processing_time_s": round(structured.get("processing_time") or 0, 2),
                },
            )
            page_count = len(structured.get("pages_text", [])) or structured.get("page_count") or 0
            if page_count:
                record_cost(
                    stage="ocr_docling",
                    provider="docling",
                    model="docling-ocr",
                    document_id=document_id,
                    units=float(page_count),
                    unit_kind="page",
                )
        except Exception as exc:
            logger.warning("[%s] Docling failed, OCR fallback: %s", document_id, exc)
            ocr = OcrService()
            ocr_result = ocr.run_ocr(s3_path)
            pages = ocr_result.get("pages", [])
            plain = "\n".join(p.get("text", "") for p in pages)
            structured = {
                "pages_text": pages,
                "plain_text": plain,
                "md_content": "",
                "hierarchy": [],
                "headings": [],
                "tables": [],
                "table_count": 0,
                "page_count": len(pages),
                "processing_time": 0,
            }
            await s3.upload_json(f"processing-artifacts/{document_id}/structure.json", structured)
            finish_step(step, {"pages": len(pages), "fallback": "ocr", "error": str(exc)[:200]})
            if pages:
                record_cost(
                    stage="ocr_fallback",
                    provider="textract",
                    model="ocr",
                    document_id=document_id,
                    units=float(len(pages)),
                    unit_kind="page",
                )

        step = start_step(document_id, 1, "structure", "document_tree", "Building document tree")
        await _update_status(document_id, "structuring")
        doc_tree = structured.get("hierarchy", [])
        with SessionLocal() as session:
            session.execute(
                text("UPDATE documents SET document_tree_json = CAST(:tree AS jsonb), updated_at = NOW() WHERE id = :id"),
                {"tree": json.dumps(doc_tree), "id": document_id},
            )
            session.commit()
        finish_step(step, {"tree_nodes": len(doc_tree)})

        step = start_step(document_id, 1, "classify", "section_classify", "Classifying sections")
        await _update_status(document_id, "classifying")
        doc_type = "generic_document"
        preset_type: str | None = None
        with SessionLocal() as session:
            preset = session.execute(
                text("SELECT document_type FROM documents WHERE id = :id"),
                {"id": document_id},
            ).first()
            if preset and preset[0]:
                preset_type = str(preset[0])
        try:
            if settings.enable_section_classification:
                classify_result = classify_sections(
                    document_id=document_id,
                    document_tree=doc_tree,
                    headings=structured.get("headings", []),
                    tables=structured.get("tables", []),
                    md_content=structured.get("md_content", ""),
                    plain_text=structured.get("plain_text", ""),
                )
                doc_type = classify_result.get("document_type", "generic_document")
                # Persist enriched_sections into the structure artifact
                structured["enriched_sections"] = classify_result.get("enriched_sections", [])
                structured["enriched_tree"] = classify_result.get("enriched_tree", [])
                await s3.upload_json(f"processing-artifacts/{document_id}/structure.json", structured)
                finish_step(
                    step,
                    {
                        "document_type": doc_type,
                        "sections_labeled": len(classify_result.get("section_labels", [])),
                    },
                )
            else:
                finish_step(step, {"document_type": doc_type, "skipped": True})
        except Exception as exc:
            finish_step(step, {"error": str(exc)[:300]}, status="failed")

        step = start_step(document_id, 1, "classify", "type_detect", "Detecting document type")
        finish_step(step, {"document_type": doc_type})

        step = start_step(
            document_id,
            1,
            "parse",
            "vehicle_llm_fallback",
            "Recovering vehicle fields (regex + LLM)",
        )
        try:
            fallback_detail = run_vehicle_fallback(
                document_id, structured, doc_type, s3_path=s3_path
            )
            finish_step(step, fallback_detail)
        except Exception as exc:
            logger.warning("[%s] Vehicle fallback failed: %s", document_id, exc)
            finish_step(step, {"error": str(exc)[:300], "required_missing": True}, status="failed")

        await _update_status(document_id, "awaiting_certification")
        cost_sum = request_cost_summary()
        if cost_sum:
            with SessionLocal() as session:
                session.execute(
                    text("""UPDATE documents 
                            SET metadata_json = COALESCE(metadata_json, '{}'::jsonb) || jsonb_build_object('processing_cost_act1', CAST(:cost AS jsonb))
                            WHERE id = :id"""),
                    {"cost": json.dumps(cost_sum), "id": document_id}
                )
                session.commit()
        await s3.upload_json(
            f"processing-artifacts/{document_id}/act1_complete.json",
            {"document_type": doc_type, "tree_nodes": len(doc_tree)},
        )
        logger.info("[%s] ACT 1 COMPLETE → awaiting_certification", document_id)
    except Exception as exc:
        logger.exception("[%s] ACT 1 FATAL: %s", document_id, exc)
        await _update_status(document_id, "failed", error=str(exc))


async def run_act2_process(document_id: str) -> None:
    """ACT 2: schema extraction followed by schema-aware embedding."""
    from ..services.cost_tracker import start_request, request_cost_summary
    start_request()
    logger.info("[%s] ACT 2 START", document_id)
    await _update_status(document_id, "schema_extraction")
    s3 = S3Service()

    try:
        structure_json = await s3.download_json(f"processing-artifacts/{document_id}/structure.json")
    except Exception as exc:
        logger.error("[%s] ACT 2: cannot load Act 1 artifacts: %s", document_id, exc)
        with SessionLocal() as session:
            row = session.execute(
                text("SELECT s3_path FROM documents WHERE id = :id"),
                {"id": document_id},
            ).first()
        if not row:
            await _update_status(document_id, "failed", error="No structure artifact")
            return
        pdf_bytes = await s3.download_bytes(row[0])
        structure_json = parse_structured(pdf_bytes)

    md_content = structure_json.get("md_content", "")
    plain_text = structure_json.get("plain_text", "")
    pages_text = structure_json.get("pages_text", [])
    page_count = structure_json.get("page_count")

    with SessionLocal() as session:
        row = session.execute(
            text("SELECT document_type, s3_path, make, model, year, metadata_json, original_filename FROM documents WHERE id = :id"),
            {"id": document_id},
        ).first()
    document_type = (row[0] if row else None) or "generic_document"
    s3_path = row[1] if row else ""
    filename = row[6] if row else ""
    
    existing_vehicle = {}
    if row:
        existing_vehicle["make"] = row[2]
        existing_vehicle["model"] = row[3]
        existing_vehicle["model_year"] = row[4]
        meta = row[5] or {}
        if isinstance(meta, dict):
            existing_vehicle["vin"] = meta.get("vin")
            existing_vehicle["chassis_id"] = meta.get("chassis_id")

    # Load sections from structure artifact for per-section extraction
    enriched_sections = structure_json.get("enriched_sections") or structure_json.get("sections", [])
    full_texts = structure_json.get("full_texts", [])

    try:
        schema_err = None
        embed_err = None
        try:
            await _run_schema_pipeline(
                document_id,
                document_type,
                md_content,
                plain_text,
                page_count,
                tables_text=structure_json.get("tables_text", ""),
                structured_tables=structure_json.get("structured_tables", []),
                sections=enriched_sections,
                full_texts=full_texts,
                existing_vehicle=existing_vehicle,
                filename=filename,
            )
        except Exception as exc:
            schema_err = exc
            logger.error("[%s] Schema pipeline failed: %s", document_id, exc)

        try:
            await _run_embedding_pipeline(document_id, s3_path, pages_text, plain_text)
        except Exception as exc:
            embed_err = exc
            logger.error("[%s] Embedding pipeline failed: %s", document_id, exc)

        if schema_err and embed_err:
            logger.error("[%s] BOTH pipelines failed: schema=%s embed=%s",
                         document_id, schema_err, embed_err)
            await _update_status(document_id, "failed", error=f"schema:{schema_err}; embed:{embed_err}")
        elif schema_err:
            logger.error("[%s] Schema pipeline failed: %s — embedding completed", document_id, schema_err)
            await _update_status(document_id, "processing_complete", error=f"schema:{schema_err}")
        elif embed_err:
            logger.error("[%s] Embedding pipeline failed: %s — schema completed", document_id, embed_err)
            await _update_status(document_id, "processing_complete", error=f"embed:{embed_err}")
        else:
            cost_sum = request_cost_summary()
            if cost_sum:
                with SessionLocal() as session:
                    session.execute(
                        text("""UPDATE documents 
                                SET metadata_json = COALESCE(metadata_json, '{}'::jsonb) || jsonb_build_object('processing_cost', CAST(:cost AS jsonb))
                                WHERE id = :id"""),
                        {"cost": json.dumps(cost_sum), "id": document_id}
                    )
                    session.commit()
            await _update_status(document_id, "processing_complete")
        logger.info("[%s] ACT 2 COMPLETE", document_id)
    except Exception as exc:
        logger.exception("[%s] ACT 2 FATAL: %s", document_id, exc)
        await _update_status(document_id, "failed", error=str(exc))


async def _run_schema_pipeline(
    document_id: str,
    document_type: str,
    md_content: str,
    plain_text: str,
    page_count: int | None,
    tables_text: str = "",
    structured_tables: list[dict] | None = None,
    sections: list[dict] | None = None,
    full_texts: list[dict] | None = None,
    existing_vehicle: dict | None = None,
    filename: str = "",
) -> None:
    from ..services.warranty_schema_extractor import extract_profile, extract_coverage_components
    from ..services.warranty_normalizer import normalize_warranty_schema, compute_completeness, compute_required_fields_missing
    from ..services.schema_validator import validate_warranty_schema
    from ..services.cost_tracker import sum_document_cost

    if not settings.enable_schema_pipeline:
        return

    step = start_step(document_id, 2, "schema", "schema_profile", "Extracting document profile")
    try:
        profile = extract_profile(
            document_id,
            md_content=md_content,
            plain_text=plain_text,
            filename=filename,
        )
        finish_step(step, {
            "make": (profile.get("applicability") or {}).get("make"),
            "program": (profile.get("warranty_program") or {}).get("program_name"),
            "stage_cost_usd": sum_document_cost(document_id),
        })
    except Exception as exc:
        finish_step(step, {"error": str(exc)[:300]}, status="failed")
        raise

    region_hint = profile.pop("coverage_region_hint", "") or ""
    step = start_step(document_id, 2, "schema", "schema_coverage", "Extracting coverage components")
    try:
        coverage_payload = extract_coverage_components(
            document_id,
            md_content=md_content,
            plain_text=plain_text,
            tables_text=tables_text,
            structured_tables=structured_tables,
            region_hint=region_hint,
        )
        finish_step(step, {
            "coverage_count": len(coverage_payload.get("coverage_components") or []),
            "source": coverage_payload.get("source", "llm"),
            "stage_cost_usd": sum_document_cost(document_id),
        })
    except Exception as exc:
        finish_step(step, {"error": str(exc)[:300]}, status="failed")
        raise

    schema: dict = {
        "document": profile.get("document") or {},
        "warranty_program": profile.get("warranty_program") or {},
        "asset_context": profile.get("asset_context") or {},
        "applicability": profile.get("applicability") or {},
        "coverage_components": coverage_payload.get("coverage_components") or [],
        "general_conditions": coverage_payload.get("general_conditions") or [],
        "general_exclusions": coverage_payload.get("general_exclusions") or [],
        "source_references": [],
        "extraction_notes": [],
    }
    if coverage_payload.get("source") == "table_bridge":
        schema["extraction_notes"].append("Coverage rows extracted deterministically from Docling tables.")

    step = start_step(document_id, 2, "schema", "schema_normalize", "Normalizing warranty schema")
    try:
        schema = normalize_warranty_schema(
            schema,
            filename=filename,
            existing_vehicle=existing_vehicle,
        )
        completeness = compute_completeness(schema)
        required_missing = compute_required_fields_missing(schema)
        finish_step(step, {
            "completeness": completeness,
            "coverage_count": len(schema.get("coverage_components") or []),
            "required_missing": required_missing,
        })
    except Exception as exc:
        finish_step(step, {"error": str(exc)[:300]}, status="failed")
        raise

    step = start_step(document_id, 2, "schema", "schema_validate", "Validating schema contract")
    ok, errors = validate_warranty_schema(schema)
    if not ok:
        schema.setdefault("extraction_notes", []).extend(errors)
    finish_step(step, {"valid": ok, "errors": errors[:5]})

    step = start_step(document_id, 2, "schema", "schema_save", "Saving master schema to database")
    asset = schema.get("asset_context") or {}
    applicability = schema.get("applicability") or {}
    make_val = applicability.get("make") or asset.get("make")
    models = applicability.get("models") or []
    model_val = asset.get("model") or (models[0] if models else None)
    year_val = None
    years = applicability.get("model_years") or {}
    if isinstance(years, dict):
        specific = years.get("specific_years") or []
        if specific:
            year_val = specific[0]
        elif years.get("from"):
            year_val = years.get("from")

    from sqlalchemy import text as sqla_text
    with SessionLocal() as session:
        session.execute(
            sqla_text("""
                UPDATE documents
                SET master_schema_json      = CAST(:schema AS jsonb),
                    completeness            = :comp,
                    required_fields_missing = :req,
                    make                    = COALESCE(:make, make),
                    model                   = COALESCE(:model, model),
                    year                    = COALESCE(:year, year),
                    metadata_json           = COALESCE(metadata_json, '{}'::jsonb)
                                              || CAST(:meta AS jsonb),
                    updated_at              = NOW()
                WHERE id = :id
            """),
            {
                "schema": json.dumps(schema),
                "comp": completeness,
                "req": required_missing,
                "make": make_val,
                "model": model_val,
                "year": year_val,
                "meta": json.dumps({k: v for k, v in {
                    "vin": asset.get("vin"),
                    "chassis_id": asset.get("chassis_id"),
                    "unit_number": asset.get("unit_number"),
                }.items() if v}),
                "id": document_id,
            },
        )
        session.commit()
    finish_step(step, {
        "coverage_count": len(schema.get("coverage_components") or []),
        "required_missing": required_missing,
        "valid": ok,
    })


async def _run_embedding_pipeline(
    document_id: str,
    s3_path: str,
    pages_text: list,
    plain_text: str,
) -> None:
    from ..services.cost_tracker import sum_document_cost

    with SessionLocal() as session:
        row = session.execute(
            text(
                "SELECT make, model, year, warranty_type, country, metadata_json "
                "FROM documents WHERE id = :id"
            ),
            {"id": document_id},
        ).first()
    metadata: dict = {}
    if row:
        metadata = {
            "make": row[0],
            "model": row[1],
            "year": row[2],
            "warrantyType": row[3],
            "country": row[4],
        }
        raw_meta = row[5] or {}
        if isinstance(raw_meta, dict):
            if raw_meta.get("vin"):
                metadata["vin"] = raw_meta["vin"]
            if raw_meta.get("chassis_id"):
                metadata["chassisId"] = raw_meta["chassis_id"]
            if raw_meta.get("unit_number"):
                metadata["unit_number"] = raw_meta["unit_number"]

    doc_type_row = None
    with SessionLocal() as session:
        dt_row = session.execute(
            text("SELECT document_type FROM documents WHERE id = :id"),
            {"id": document_id},
        ).first()
        doc_type_row = dt_row[0] if dt_row else None

    if not metadata.get("vin") and plain_text:
        parsed = parse_vin_chassis_from_text(plain_text)
        if parsed.get("vin"):
            metadata["vin"] = parsed["vin"]
        if parsed.get("chassis_id"):
            metadata["chassisId"] = parsed["chassis_id"]

    master: dict = {}
    with SessionLocal() as session:
        schema_row = session.execute(
            text("SELECT master_schema_json FROM documents WHERE id = :id"),
            {"id": document_id},
        ).first()
        if schema_row and isinstance(schema_row[0], dict):
            master = schema_row[0]

    step = start_step(document_id, 2, "embedding", "chunk_generate", "Generating chunks")
    try:
        if has_usable_warranty_schema(master):
            flat = build_warranty_chunks(master, metadata, document_id)
            source = "warranty_schema"
        elif has_usable_schema(master):
            flat = build_schema_chunks(master, metadata, document_id)
            source = "schema"
        elif pages_text:
            flat = chunk_pages_flat(pages_text)
            source = "docling_tables"
        else:
            flat = chunk_text(plain_text)
            source = "plain_text"

        invoice_profile = (master.get("profiles", {}) or {}).get("repair_invoice", {})
        if invoice_profile.get("line_items") or invoice_profile.get("totals"):
            from ..services.invoice_chunk_builder import build_invoice_chunks

            inv_chunks = build_invoice_chunks(invoice_profile, metadata, document_id)
            flat = flat + inv_chunks
            source = f"{source}+invoice"
            logger.info("[%s] appended %d invoice chunks", document_id, len(inv_chunks))

        if settings.enable_parent_child:
            chunks = build_parent_child_chunks(flat, document_id)
        else:
            chunks = flat
        finish_step(step, {"chunk_count": len(chunks), "source": source})
    except Exception as exc:
        finish_step(step, {"error": str(exc)[:300]}, status="failed")
        raise

    step = start_step(document_id, 2, "embedding", "metadata_enrich", "Enriching metadata")
    qdrant = QdrantService()
    filename = Path(s3_path).name if s3_path else f"{document_id}.pdf"
    chunks = prepare_chunks_for_upsert(
        chunks,
        plain_text,
        enable_contextual=settings.enable_contextual_retrieval,
        enable_sparse=qdrant.hybrid,
        document_id=document_id,
    )
    enriched = []
    for chunk in chunks:
        item = dict(chunk)
        if not item.get("structuredMeta"):
            item["structuredMeta"] = parse_chunk_structured_meta(item)
        item["repository"] = "certified"
        item["documentId"] = document_id
        item["filename"] = filename
        payload_extra = {
            "make": metadata.get("make"),
            "model": metadata.get("model"),
            "year": metadata.get("year"),
            "country": metadata.get("country"),
            "warrantyType": metadata.get("warrantyType"),
            "vin": metadata.get("vin"),
            "chassisId": metadata.get("chassisId"),
        }
        meta = item.get("structuredMeta") or {}
        if isinstance(meta, dict):
            for key in (
                "coverage_id", "coverage_type", "system", "subsystem",
                "component_group", "asset_category", "mileage_limit", "mileage_unit",
            ):
                if meta.get(key) is not None:
                    payload_extra[key] = meta[key]
        item.update(payload_extra)
        enriched.append(item)
    finish_step(step, {"enriched": len(enriched)})

    step = start_step(document_id, 2, "embedding", "embed_generate", "Creating embeddings (OpenAI)")
    finish_step(step, {
        "chunks": len(enriched),
        "model": "text-embedding-3-small",
        "stage_cost_usd": sum_document_cost(document_id),
    })

    step = start_step(document_id, 2, "embedding", "qdrant_index", "Indexing (Qdrant)")
    try:
        qdrant.upsert_chunks(document_id, enriched)
        finish_step(step, {"upserted": len(enriched), "collection": settings.qdrant_collection})
    except Exception as exc:
        finish_step(step, {"error": str(exc)[:300]}, status="failed")
        raise


async def process_document(document_id: str, s3_path: str | None = None) -> None:
    """Legacy entry point → Act 1 only when gate_heavy_on_certify is enabled."""
    if settings.gate_heavy_on_certify:
        await run_act1_parse(document_id, s3_path)
    else:
        await _legacy_process_document(document_id, s3_path)


async def _legacy_process_document(document_id: str, s3_path: str | None = None) -> None:
    """Full single-pass pipeline (pre-plan behavior) when gate is disabled."""
    from ..services.extraction_service import ExtractionService

    s3 = S3Service()
    ocr = OcrService()
    extractor = ExtractionService()
    qdrant = QdrantService()

    if not s3_path:
        with SessionLocal() as session:
            row = session.execute(text("SELECT s3_path FROM documents WHERE id = :id"), {"id": document_id}).first()
            if not row:
                return
            s3_path = row[0]

    try:
        await _update_status(document_id, "ocr_in_progress")
        ocr_result = ocr.run_ocr(s3_path)
        plain_text = "\n".join(item["text"] for item in ocr_result.get("pages", []))
        metadata = extractor.extract_metadata(plain_text)
        ocr_pages = ocr_result.get("pages", [])
        chunks = chunk_pages(ocr_pages, document_id=document_id) if ocr_pages else chunk_text(plain_text)
        chunks = prepare_chunks_for_upsert(chunks, plain_text, enable_contextual=settings.enable_contextual_retrieval, enable_sparse=qdrant.hybrid)
        enriched = []
        for chunk in chunks:
            item = dict(chunk)
            item["repository"] = "pending_review"
            item["documentId"] = document_id
            enriched.append(item)
        qdrant.upsert_chunks(document_id, enriched)
        new_s3_path = f"pending-review/{document_id}/original.pdf"
        await s3.move_object(s3_path, new_s3_path)
        with SessionLocal() as session:
            session.execute(
                text(
                    "UPDATE documents SET s3_path = :s3_path, processing_status = 'ready_for_review', "
                    "current_repository = 'pending_review', updated_at = NOW() WHERE id = :id"
                ),
                {"s3_path": new_s3_path, "id": document_id},
            )
            session.commit()
    except Exception as error:
        await _update_status(document_id, "failed", error=str(error))
