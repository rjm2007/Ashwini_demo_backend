"""Defect → match → disambiguate → eligibility → decision workflow."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
import uuid
from pathlib import Path

from sqlalchemy import text

from .coverage_decider import compute_clause_eligibility, decide_one_clause
from .defect_classifier import classify_defect, interpret_defect, _parse_json, _load_prompt
from .defect_matcher import match_coverage_rows
from .document_resolver import resolve_documents_by_make_model_year
from .retriever import retrieve_chunks
from ..database import SessionLocal
from ..services.llm_service import LlmService

logger = logging.getLogger(__name__)

_LIST_RE = re.compile(
    r"\b(list|show|all)\b.*\b(coverage|coverages|components|warranties)\b", re.IGNORECASE
)
_CODE_RE = re.compile(r"\b([A-Z]{1,3}\d{1,4}[A-Z]?)\b")
_DEFECT_RE = re.compile(
    r"\b(broken|leak|noise|failed|failure|defect|issue|problem|hard to|won'?t|doesn'?t|overheat|sluggish)\b",
    re.IGNORECASE,
)

# Words that signal the user is CONTINUING a previous defect question rather than starting a new one.
_FOLLOWUP_RE = re.compile(
    r"\b(now|again|check|recheck|re-?check|covered|is it|are we|what about|filled|added|"
    r"updated|entered|provided|yes|please check|the same|this|it|asked|meant|wrong|"
    r"instead|not that|that one|i did|done)\b",
    re.IGNORECASE,
)

def _looks_like_defect(text: str) -> bool:
    """A message is a fresh defect if it names a symptom or component."""
    t = (text or "").lower()
    if _DEFECT_RE.search(t):
        return True
    for w in ("engine", "transmission", "brake", "air condition", "ac ", "a/c", "frame",
              "cab", "axle", "driveline", "clutch", "exhaust", "aftertreatment", "cooling",
              "leak", "overheat", "knock", "noise", "crack", "worn", "damage", "not working",
              "not functioning", "not cooling", "won't", "wont", "doesn't", "stuck", "frozen",
              "steering", "steer", "stering", "steerin", "suspension", "alignment", "tie rod",
              "knuckle", "ball joint", "wheel bearing", "shock", "strut", "smoke", "vibration",
              "grinding", "rattle", "leaking", "hard to turn", "not turning", "differential"):
        if w in t:
            return True
    return False

def _recall_last_defect(conversation_history: list[dict]) -> str | None:
    """Scan history backwards for the most recent USER message that was a real defect."""
    for item in reversed(conversation_history or []):
        if (item.get("role") or "") != "user":
            continue
        content = item.get("content") or ""
        # skip our own follow-up echoes and selection messages
        if content.lower().startswith("selected coverage"):
            continue
        if _looks_like_defect(content):
            return content
    return None

def _is_followup_continuation(question: str, intent: str) -> bool:
    """True when the user is continuing a prior defect (not starting a new one)."""
    if _looks_like_defect(question):
        return False   # it's a fresh defect; handle normally
    if intent in ("followup_clarification", "warranty_coverage", "ambiguous"):
        return bool(_FOLLOWUP_RE.search(question or ""))
    return bool(_FOLLOWUP_RE.search(question or ""))

def _collect_rows(docs: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for doc in docs:
        for row in (doc.get("master_schema") or {}).get("coverage_components") or []:
            item = dict(row)
            item["_documentId"] = doc["documentId"]
            rows.append(item)
    return rows

def _period_label(row: dict) -> str | None:
    period = row.get("coverage_period") or {}
    parts: list[str] = []
    if period.get("duration_months") is not None:
        parts.append(f"{period['duration_months']} months")
    elif period.get("duration_text"):
        parts.append(str(period["duration_text"]).split("/")[0].strip())
    if period.get("mileage_unit") == "unlimited":
        parts.append("Unlimited miles")
    elif period.get("mileage_limit") is not None:
        unit = period.get("mileage_unit") or "miles"
        parts.append(f"{int(period['mileage_limit']):,} {unit}")
    return " / ".join(parts) if parts else None

def _eligibility_hint(row: dict) -> str | None:
    period = row.get("coverage_period") or {}
    need: list[str] = []
    if period.get("duration_months") is not None:
        need.append("purchase date")
    if period.get("mileage_limit") is not None:
        need.append("current mileage")
    if not need:
        return "No date or mileage needed."
    return f"To determine active coverage, provide {' and '.join(need)}."

def _load_doc_exclusions(document_id: str | None) -> tuple[list[dict], list[dict]]:
    if not document_id:
        return [], []
    try:
        with SessionLocal() as session:
            row = session.execute(
                text("SELECT master_schema_json FROM documents WHERE id = :id"),
                {"id": document_id},
            ).first()
        if not row or not row[0]:
            return [], []
        schema = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        return (
            list(schema.get("general_exclusions") or [])[:5],
            list(schema.get("general_conditions") or [])[:5],
        )
    except Exception as exc:
        logger.warning("Failed to load exclusions for %s: %s", document_id, exc)
        return [], []

def _document_name(document_id: str | None) -> str | None:
    if not document_id:
        return None
    try:
        with SessionLocal() as session:
            row = session.execute(
                text("SELECT master_schema_json, filename FROM documents WHERE id = :id"),
                {"id": document_id},
            ).first()
        if not row:
            return None
        schema = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
        filename = row[1]
        return schema.get("warranty_program", {}).get("program_name") or filename
    except Exception as exc:
        logger.warning("Failed to load document name for %s: %s", document_id, exc)
        return None

def handle_list_coverage(context: dict, document_id: str | None) -> dict:
    docs = resolve_documents_by_make_model_year(
        context.get("make"),
        context.get("model"),
        context.get("year"),
        document_id=document_id,
    )
    rows = _collect_rows(docs)
    items = []
    for r in rows:
        items.append(
            {
                "coverage_id": r.get("coverage_id"),
                "coverage_name": r.get("coverage_name"),
                "coverage_type": r.get("coverage_type"),
                "coverage_period": r.get("coverage_period"),
                "period_label": _period_label(r),
                "eligibility_hint": _eligibility_hint(r),
                "limit_of_liability": r.get("limit_of_liability"),
                "documentId": r.get("_documentId"),
            }
        )
    def _format_period(it: dict) -> str:
        label = it.get("period_label")
        if isinstance(label, str) and label.strip() and label.strip().lower() != "none":
            return label.strip()
        period = it.get("coverage_period")
        if isinstance(period, dict):
            text = period.get("duration_text")
            if isinstance(text, str) and text.strip():
                return text.strip()
            parts = []
            months = period.get("duration_months")
            if months:
                parts.append(f"{months} months")
            miles = period.get("mileage_limit")
            if miles:
                unit = period.get("mileage_unit") or "miles"
                parts.append(f"{miles:,} {unit}")
            if parts:
                return " / ".join(parts)
        return ""

    if items:
        lines = [f"This warranty includes **{len(items)}** covered components:", ""]
        for it in items:
            cid = it.get("coverage_id") or "—"
            name = it.get("coverage_name") or "Unnamed coverage"
            period = _format_period(it)
            period_text = f" — {period}" if period else ""
            lines.append(f"- **{cid}** {name}{period_text}")
        list_answer = "\n".join(lines)
    else:
        list_answer = "I couldn't find any coverage rows for this document."

    return {
        "responseType": "coverage_list",
        "coverages": items,
        "answer": list_answer,
        "evidence": [],
        "confidence": 0.9,
        "filters": {},
        "context": context,
    }

def handle_coverage_lookup(question: str, context: dict, document_id: str | None) -> dict | None:
    codes = _CODE_RE.findall(question or "")
    if not codes:
        return None
    code = codes[0]
    docs = resolve_documents_by_make_model_year(
        context.get("make"),
        context.get("model"),
        context.get("year"),
        document_id=document_id,
    )
    rows = [r for r in _collect_rows(docs) if str(r.get("coverage_id")).upper() == code.upper()]
    if not rows:
        # Not a real coverage code for this vehicle (often a false-positive token such as a model
        # number). Fall through to the defect / retrieval path instead of dead-ending the user.
        return None
    row = rows[0]
    period = row.get("coverage_period") or {}
    answer = (
        f"{row.get('coverage_name')} ({code}): "
        f"{period.get('duration_text') or 'see document for period details'}."
    )
    return {
        "responseType": "answer",
        "answer": answer,
        "coverage": row,
        "evidence": [],
        "confidence": 0.85,
        "filters": {"coverage_id": code},
        "context": context,
    }

def answer_followup_question(
    question: str,
    active_defect: str,
    last_result: dict,
    conversation_history: list[dict] | None,
) -> dict:
    """A follow-up QUESTION about an existing defect verdict ("explain in detail", "why is it
    expired", "what does U06A mean") — answered conversationally using the result that was
    already computed, without re-running matching/eligibility/retrieval from scratch. This is
    what makes "explain in detail" actually explain, instead of replaying the same card."""
    llm = LlmService()
    history_text = "\n".join(
        f"{m.get('role')}: {m.get('content')}" for m in (conversation_history or [])[-6:]
    )
    payload = json.dumps({
        "reported_defect": active_defect,
        "prior_result": last_result,
        "recent_conversation": history_text,
        "follow_up_question": question,
    })
    out = llm.small_model_call(payload, _load_prompt("defect_followup.txt"), stage="defect_followup")
    j = _parse_json(out) or {}
    answer = j.get("answer") or "I don't have anything more to add on that — try asking about a specific coverage by name."
    return {
        "responseType": "answer",
        "answer": answer,
        "evidence": [],
        "confidence": 0.7,
        "filters": {},
        "context": {"activeDefect": active_defect, "lastResult": last_result},
    }

def answer_defect_thread(
    question: str,
    document_id: str,
    context: dict | None,
    conversation_history: list[dict],
) -> dict:
    context = context or {}
    target = question
    if not _looks_like_defect(question):
        active = context.get("activeDefect") or _recall_last_defect(conversation_history)
        if active:
            last_result = context.get("lastResult")
            if last_result:
                return answer_followup_question(question, active, last_result, conversation_history)
            target = active
    return handle_defect_workflow(target, context, document_id, conversation_history)

def route_specialized_query(
    question: str,
    context: dict | None,
    document_id: str | None,
    conversation_history: list[dict],
    intent: str,
    classification: dict | None = None,
) -> dict | None:
    context = context or {}
    classification = classification or {}

    # Defect handling moved to Defect tab

    if (question or "").strip().lower().startswith("/defect"):
        return {
            "responseType": "answer",
            "answer": "ℹ️ **Defect routing has moved.** To evaluate a specific defect against this warranty, please use the **Defects** tab in the sidebar.",
            "evidence": [],
            "confidence": 0.99,
            "filters": {},
            "context": context
        }

    if intent == "list_coverage" or _LIST_RE.search(question or ""):
        return handle_list_coverage(context, document_id)
    if _CODE_RE.search(question or ""):
        lookup = handle_coverage_lookup(question, context, document_id)
        if lookup:
            return lookup
            
    if intent == "defect_report" or _looks_like_defect(question) or (classification.get("confidence", 1.0) < 0.6 and _DEFECT_RE.search(question or "")):
        return {
            "responseType": "answer",
            "answer": "ℹ️ **Defect routing has moved.** To evaluate a specific defect against this warranty, please use the **Defects** tab in the sidebar.",
            "evidence": [],
            "confidence": 0.99,
            "filters": {},
            "context": context
        }
    return None


def _is_secondary_row(r):
    """Towing / roadside / rental / info-only / administrative are benefits, not component coverage."""
    ct = str(r.get("coverage_type") or "").lower()
    sys = str((r.get("coverage_hierarchy") or {}).get("system") or "").lower()
    name = str(r.get("coverage_name") or "").lower()
    if ct in ("towing", "information only", "roadside", "rental"):
        return True
    if sys == "administrative":
        return True
    if any(w in name for w in ("towing", "roadside", "rental", "trip interruption", "info only")):
        return True
    return False

def _is_secondary_result(c):
    ct = str(c.get("coverage_type") or "").lower()
    name = str(c.get("warranty_heading") or "").lower()
    return ct in ("towing", "information only", "roadside", "rental") or any(
        w in name for w in ("towing", "roadside", "rental", "trip interruption", "info only")
    )

def _name_fallback_match(reported_defect, interp, all_rows):
    """Safety net when the hierarchy match finds nothing (e.g. air conditioning).
    Matches a coverage row by the SYSTEM the defect clearly belongs to."""
    text = " ".join([
        str(reported_defect or ""),
        str(interp.get("interpreted_component") or ""),
        str(interp.get("defect_category") or ""),
    ]).lower()
    SYS_SYNONYMS = {
        "hvac": ["air condition", "a/c", "hvac", "cooling", "heater", "freon", "climate", "ac sealed"],
        "powertrain": ["engine", "transmission", "motor", "gear", "clutch", "driveline", "axle", "differential", "water pump"],
        "chassis": ["brake", "frame", "crossmember", "suspension", "steering"],
        "emission": ["emission", "aftertreatment", "dpf", "def", "exhaust", "scr", "egr"],
        "cab": ["cab", "corrosion", "cab structure"],
        "electrical": ["battery", "alternator", "starter", "charging", "wiring"],
    }
    wanted = {sys for sys, kws in SYS_SYNONYMS.items() if any(k in text for k in kws)}
    if not wanted:
        return []
    out = []
    for r in all_rows:
        sys = str((r.get("coverage_hierarchy") or {}).get("system") or "").lower()
        ct = str(r.get("coverage_type") or "").lower()
        if sys in wanted or ct in wanted:
            rr = dict(r)
            rr["_match_score"] = 0.5
            out.append(rr)
    # real coverage first, secondary last
    out.sort(key=lambda r: (_is_secondary_row(r), -(r.get("_match_score") or 0.0)))
    return out[:3]


def _request_id():
    import datetime, random
    return "WRG-" + datetime.date.today().strftime("%Y%m%d") + "-" + str(random.randint(0, 999999)).zfill(6)

def _check_exclusions(interp, doc_exclusions):
    """Score the defect against exclusions. Wear/accident always strong even without an exclusions section."""
    results = []
    strong = False
    if interp.get("is_wear_or_consumable"):
        strong = True
        title = next((e.get("title") for e in (doc_exclusions or []) if "wear" in (e.get("title", "").lower())), "Normal Wear Items")
        page = next((e.get("page") for e in (doc_exclusions or []) if "wear" in (e.get("title", "").lower())), None)
        results.append({"warranty_heading": title, "page_number": page, "exclusion_confidence_score": 0.95,
                        "exclusion_result": "Strong exclusion found",
                        "explanation": "The reported part is a wear/consumable item and is excluded when replacement is due to normal wear."})
    elif interp.get("is_accident_or_misuse"):
        strong = True
        title = next((e.get("title") for e in (doc_exclusions or []) if any(w in (e.get("title", "").lower()) for w in ("accident", "misuse", "collision", "abuse"))), "Accident & Misuse")
        page = next((e.get("page") for e in (doc_exclusions or []) if any(w in (e.get("title", "").lower()) for w in ("accident", "misuse", "collision", "abuse"))), None)
        results.append({"warranty_heading": title, "page_number": page, "exclusion_confidence_score": 0.92,
                        "exclusion_result": "Strong exclusion found",
                        "explanation": "The failure appears to result from accident or misuse, which warranty excludes."})
    else:
        title = (doc_exclusions or [{}])[0].get("title", "General Warranty Exclusions") if doc_exclusions else "General Warranty Exclusions"
        page = (doc_exclusions or [{}])[0].get("page") if doc_exclusions else None
        results.append({"warranty_heading": title, "page_number": page, "exclusion_confidence_score": 0.4,
                        "exclusion_result": "No strong exclusion found",
                        "explanation": "No clear indication of abuse, lack of maintenance, accident damage, or non-OEM modification."})
    return {"exclusions_checked": results, "strong_exclusion": strong}

def _fmt_date(s):
    try:
        import datetime
        return datetime.date.fromisoformat(s).strftime("%B %d, %Y")
    except Exception:
        return s

def _clause_explanation(decision, row, elig, interp_public):
    name = row.get("coverage_name")
    if decision == "INFORMATION_ONLY":
        return f"Relates to your {name} coverage. Add the truck's purchase date and current mileage in the fields above the chat box, then ask again to check it."
    if decision == "COVERED":
        return f"Covered under your {name} coverage — your truck is within the limits."
    if decision == "POSSIBLY_COVERED":
        return f"Matches your {name} coverage, but your truck is outside the time or mileage limit, so it needs a quick review."
    return f"Your {name} coverage does not apply here — either an exclusion applies, the defect doesn't match this coverage, or your truck is well outside this coverage's time or mileage limit."

def _confidence_word(score):
    if score is None:
        return "possible match"
    if score >= 0.85:
        return "strong match"
    if score >= 0.65:
        return "likely match"
    return "possible match"

def _verdict_header(decision):
    return {
        "COVERED": "✅ **Covered**",
        "POSSIBLY_COVERED": "⚠️ **Possibly Covered — Needs Review**",
        "NOT_COVERED": "❌ **Not Covered**",
        "INFORMATION_ONLY": "ℹ️ **We need a bit more information**",
    }.get(decision, "ℹ️ **Result**")

def _limits_phrase(e):
    dm = e.get("duration_months")
    ml = e.get("warranty_mileage_limit")
    parts = []
    if dm is not None:
        parts.append(f"up to {dm} months")
    if ml is not None:
        parts.append(f"{int(ml):,} miles")
    if not parts:
        return "no time or mileage limit"
    s = " and ".join(parts)
    if e.get("warranty_expiration_date"):
        s += f" (your coverage runs out {_fmt_date(e['warranty_expiration_date'])})"
    return s

def _truck_status_phrase(e):
    bits = []
    if e.get("purchase_date"):
        bits.append(f"purchased {_fmt_date(e['purchase_date'])}")
    if e.get("current_mileage") is not None:
        bits.append(f"now at {int(e['current_mileage']):,} miles")
    if not bits:
        return None
    status = []
    if e.get("time_eligible") is True:
        status.append("within the time limit")
    elif e.get("time_eligible") is False:
        status.append("past the time limit")
    if e.get("mileage_eligible") is True:
        status.append("within the mileage limit")
    elif e.get("mileage_eligible") is False:
        status.append("over the mileage limit")
    tail = (" — " + ", ".join(status)) if status else ""
    return ", ".join(bits) + tail

def _why_possible(e):
    te, me = e.get("time_eligible"), e.get("mileage_eligible")
    if te is False and me is False:
        return "your truck is past both the time and mileage limits"
    if te is False:
        return "your truck is past the time limit"
    if me is False:
        return "your truck is over the mileage limit"
    return "we could not fully confirm eligibility"

def _multi_user_message(reported_defect, interp_public, clause_results, excl, info_only):
    component = interp_public.get("interpreted_component") or "issue"
    real = [c for c in clause_results if not _is_secondary_result(c)]
    primary = (real or clause_results)[0]
    decision = "INFORMATION_ONLY" if info_only else primary["decision"]
    heading = primary["warranty_heading"]
    lines = [_verdict_header(decision), ""]

    # 1) one plain sentence telling the user what this means
    if info_only:
        lines.append(
            f"Your **{component}** problem looks like it falls under your **{heading}** coverage. "
            f"To tell you for sure, add the truck's **purchase date** and **current mileage** in the "
            f"fields just above the chat box, then send your question again."
        )
        return "\n".join(lines)
    if decision == "COVERED":
        lines.append(f"Good news — your **{component}** problem is **covered** under your **{heading}** coverage.")
    elif decision == "POSSIBLY_COVERED":
        lines.append(
            f"Your **{component}** problem falls under your **{heading}** coverage, but "
            f"{_why_possible(primary['asset_eligibility'])}, so it needs a quick review before it can be approved."
        )
    elif decision == "NOT_COVERED":
        lines.append(f"Unfortunately, your **{component}** problem is **not covered** under this warranty.")

    # 2) plain details
    e = primary["asset_eligibility"]
    lines.append("")
    lines.append("**Here is why:**")
    cov = _limits_phrase(e)
    lines.append(f"- Your **{heading}** coverage lasts {cov}.")
    truck = _truck_status_phrase(e)
    if truck:
        lines.append(f"- Your truck was {truck}.")
    if decision == "COVERED":
        lines.append("- Your truck is within the limits, so this repair should be covered. ✅")
    elif decision == "POSSIBLY_COVERED":
        lines.append("- A warranty reviewer should confirm this, or check whether you have an extended warranty. ⚠️")

    # 3) other real coverage that may also apply
    others = [c for c in real if c is not primary][:2]
    if others:
        lines.append("")
        lines.append("**Other coverage that may also apply:**")
        for c in others:
            word = _confidence_word(c.get("context_confidence_score"))
            verdict = c["decision"].replace("_", " ").lower()
            lines.append(f"- Your **{c['warranty_heading']}** coverage ({verdict}, {word}).")

    # 4) exclusion note (always shown)
    ex = (excl.get("exclusions_checked") or [{}])[0]
    if ex.get("exclusion_result") == "Strong exclusion found":
        lines.append("")
        lines.append(f"⚠️ **Exclusion found:** {ex.get('explanation', '')}")
    else:
        conf = int((ex.get("exclusion_confidence_score") or 0) * 100)
        lines.append("")
        lines.append(f"✅ **Exclusion check:** No exclusion found ({conf}%) — {ex.get('explanation', '')}")

    # 5) small reference for staff (codes live here, not in the headline)
    codes = ", ".join(str(c.get("coverage_id")) for c in (real or clause_results) if c.get("coverage_id"))
    if codes:
        lines.append("")
        lines.append(f"_For warranty staff — coverage reference: {codes}_")
    return "\n".join(lines)

def _clause_context(reported_defect, row, document_id, llm):
    """Build the plain-language summary + why_matched + confidence for ONE clause."""
    chunks = retrieve_chunks(
        f"{row.get('coverage_name')} {reported_defect}",
        {"documentId": document_id, "coverage_id": row.get("coverage_id")},
        list_mode=False,
    )
    top = (chunks or [{}])[0].get("payload", {}) if chunks else {}
    out = llm.small_model_call(
        __import__("json").dumps({
            "reported_defect": reported_defect,
            "warranty_heading": row.get("coverage_name"),
            "chunk_text": top.get("text") or (row.get("source_reference") or {}).get("text_reference", ""),
        }),
        _load_prompt("context_why_matched.txt"),
        stage="why_matched",
        document_id=document_id,
    )
    j = _parse_json(out)
    conf = j.get("context_confidence_score")
    if conf is None:
        conf = row.get("_match_score") or 0.6
    return {
        "page_number": (row.get("source_reference") or {}).get("page") or top.get("page"),
        "chunk_id": top.get("chunk_id") or f"{document_id}-CHUNK-{str(row.get('coverage_id'))}",
        "matched_context_summary": j.get("matched_context_summary", ""),
        "why_matched": j.get("why_matched", ""),
        "context_confidence_score": round(float(conf), 2),
    }

def handle_defect_workflow(question, context, document_id, conversation_history):
    import json as _json
    llm = LlmService()
    context = context or {}
    eligibility = context.get("eligibility") or {}
    reported_defect = question
    # If this turn is a bare follow-up but we were called with the recalled defect, that recalled
    # text is already in `question` (see route_specialized_query). Nothing else needed here.

    # 1) resolve the document (chat is document-scoped)
    docs = resolve_documents_by_make_model_year(
        context.get("make"), context.get("model"), context.get("year"), document_id=document_id
    )
    if not docs:
        return {"responseType": "answer",
                "answer": "I need a certified warranty document to evaluate this defect.",
                "evidence": [], "confidence": 0.3, "filters": {}, "context": context}

    doc = docs[0]
    schema = doc.get("master_schema") or {}
    all_rows = _collect_rows(docs)
    document_name = (schema.get("document") or {}).get("source_file") or doc.get("filename") or "Warranty Document"

    # 2) build the asset (make/model/year from the document; date/mileage from the chat sidebar)
    asset = {
        "make": (schema.get("asset_context") or {}).get("make") or (schema.get("applicability") or {}).get("make"),
        "model": (schema.get("asset_context") or {}).get("model"),
        "model_year": (schema.get("applicability") or {}).get("model_years", {}).get("from"),
        "vin": (schema.get("asset_context") or {}).get("vin"),
        "purchase_date": eligibility.get("purchase_date"),
        "current_mileage": eligibility.get("current_mileage"),
        "_applicability": schema.get("applicability") or {},
    }

    # 3) interpret the defect (plain-language component + failure type + category)
    interp = interpret_defect(reported_defect, asset, llm)
    interp_public = {
        "reported_defect": reported_defect,
        "interpreted_component": interp.get("interpreted_component"),
        "interpreted_failure_type": interp.get("interpreted_failure_type"),
        "defect_category": interp.get("defect_category"),
    }

    # 4) match the top clauses (matcher caps at 3 and requires system+subsystem)
    matched_rows = match_coverage_rows(all_rows, interp.get("candidate_targets") or [])
    # 4b) safety net: if nothing matched, try a system-keyword fallback (rescues air conditioning, etc.)
    if not matched_rows:
        matched_rows = _name_fallback_match(reported_defect, interp, all_rows)
    # 4c) put real component coverage ABOVE secondary benefits (towing / roadside / rental / info)
    matched_rows.sort(key=lambda r: (_is_secondary_row(r), -(r.get("_match_score") or 0.0)))
    matched_rows = matched_rows[:3]

    # 5) defect-level exclusion check (wear / accident / misuse). Shared across clauses.
    doc_excl, _ = _load_doc_exclusions(document_id)
    excl = _check_exclusions(interp, doc_excl)
    strong_exclusion = excl.get("strong_exclusion") is True

    # 6) INFORMATION ONLY: warranty has limits but no date AND no mileage
    has_limited = any(((r.get("coverage_period") or {}).get("duration_months") is not None or
                       (r.get("coverage_period") or {}).get("mileage_limit") is not None) for r in matched_rows)
    no_inputs = not eligibility.get("purchase_date") and not eligibility.get("current_mileage")

    # 7) no clause matched at all — tell the user what IS covered (plain language)
    if not matched_rows:
        covered_systems = sorted({
            str((r.get("coverage_hierarchy") or {}).get("system") or r.get("coverage_type") or "").strip()
            for r in all_rows
        } - {""})
        systems_text = ", ".join(s.lower() for s in covered_systems) or "the listed components"
        return {"responseType": "answer",
                "answer": ("ℹ️ **This warranty does not appear to cover that problem.**\n\n"
                           f"This warranty covers: {systems_text}. "
                           "If you believe this should be covered, a warranty reviewer can take a closer look."),
                "defect_interpretation": interp_public,
                "evidence": [], "confidence": 0.35, "filters": {},
                "context": {**context, "activeDefect": reported_defect}}

    # 8) build ONE result per matched clause (answer ALL of them)
    clause_results = []
    for rank, row in enumerate(matched_rows, start=1):
        cx = _clause_context(reported_defect, row, document_id, llm)
        if has_limited and no_inputs:
            elig = compute_clause_eligibility(row, asset)   # most fields null
            decision = "INFORMATION_ONLY"
        else:
            elig = compute_clause_eligibility(row, asset)
            decision = decide_one_clause(elig, cx["context_confidence_score"], strong_exclusion)
        clause_results.append({
            "rank": rank,
            "coverage_id": row.get("coverage_id"),
            "warranty_heading": row.get("coverage_name"),     # PLAIN LANGUAGE label (not the code)
            "coverage_type": row.get("coverage_type"),
            "context_confidence_score": cx["context_confidence_score"],
            "matched_context_summary": cx["matched_context_summary"],
            "why_matched": cx["why_matched"],
            "page_number": cx["page_number"],
            "chunk_id": cx["chunk_id"],
            "decision": decision,
            "asset_eligibility": elig,
            "explanation": _clause_explanation(decision, row, elig, interp_public),
        })

    # sort by confidence, re-rank
    clause_results.sort(key=lambda c: c["context_confidence_score"], reverse=True)
    for i, c in enumerate(clause_results, start=1):
        c["rank"] = i

    # 9) overall summary — the VERDICT comes from real component coverage, not a towing/info benefit
    real_results = [c for c in clause_results if not _is_secondary_result(c)]
    primary = (real_results or clause_results)[0]
    overall_decision = "INFORMATION_ONLY" if (has_limited and no_inputs) else primary["decision"]
    user_message = _multi_user_message(reported_defect, interp_public, clause_results, excl, has_limited and no_inputs)

    return {
        "responseType": "multi_decision",
        "request_id": _request_id(),
        "primary_decision": overall_decision,
        "overall_confidence_score": primary["context_confidence_score"],
        "defect_interpretation": interp_public,
        "asset": {k: asset.get(k) for k in ("make", "model", "model_year", "vin", "purchase_date", "current_mileage")},
        "exclusions_checked": excl.get("exclusions_checked", []),
        "clause_results": clause_results,
        "user_message": user_message,
        # back-compat fields so the old card still has something:
        "coverageDecision": overall_decision,
        "answer": user_message,
        "confidence": primary["context_confidence_score"],
        "filters": {},
        "context": {
            **context,
            "selectedCoverageId": None,
            "activeDefect": reported_defect,
            "lastResult": {
                "reported_defect": reported_defect,
                "primary_decision": overall_decision,
                "clause_results": [
                    {
                        "warranty_heading": c.get("warranty_heading"),
                        "coverage_id": c.get("coverage_id"),
                        "decision": c.get("decision"),
                        "why_matched": c.get("why_matched"),
                        "explanation": c.get("explanation"),
                        "asset_eligibility": c.get("asset_eligibility"),
                    }
                    for c in clause_results
                ],
                "exclusions_checked": excl.get("exclusions_checked", []),
            },
        },
    }
