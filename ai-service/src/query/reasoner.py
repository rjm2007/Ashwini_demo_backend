import json
from datetime import date
from pathlib import Path
from ..services.llm_service import LlmService


def reason_over_evidence(
    question: str,
    history: list[dict],
    chunks: list[dict],
    *,
    table_mode: bool = False,
    schema_facts: list[dict] | None = None,
    document_type: str | None = None,
) -> dict:
    """This function asks the large model to answer strictly from evidence chunks."""
    llm = LlmService()
    prompts_dir = Path(__file__).resolve().parent / "prompts"
    prompt_name = "table_list_reasoning.txt" if table_mode else "final_reasoning.txt"
    prompt = (prompts_dir / prompt_name).read_text(encoding="utf-8")
    parts = []
    for index, item in enumerate(chunks):
        p = item["payload"]
        header = f"[{index + 1}] page={p.get('pageNumber')} doc={p.get('filename', '?')}"
        if p.get("chunkType"):
            header += f" type={p.get('chunkType')}"
        codes = p.get("coverageCodes") or []
        if codes:
            header += f" codes={','.join(str(c) for c in codes[:8])}"
        if p.get("sectionTitle"):
            header += f" section={p.get('sectionTitle')}"
        body = p.get("chunkText") or ""
        snippet = p.get("retrievalSnippet")
        if snippet and snippet != body:
            parts.append(f"{header}\nmatched_row={snippet}\ncontext=\n{body}")
        else:
            parts.append(f"{header}\ntext={body}")
    formatted_chunks = "\n\n".join(parts)
    formatted_history = "\n".join([f"{item.get('role')}: {item.get('content')}" for item in history])

    schema_block = ""
    if schema_facts:
        lines: list[str] = []
        for fact in schema_facts:
            lines.append(f"## Vehicle: {fact.get('vehicle') or 'Unknown vehicle'} (doc {fact.get('documentId')})")
            for code in fact.get("coverage_codes", []):
                limit = " / ".join(
                    part for part in (code.get("duration"), code.get("distance")) if part
                )
                period = f"{code.get('start_date') or '?'} to {code.get('end_date') or '?'}"
                lines.append(
                    f"- {code.get('code')}: {code.get('description', '')} | {limit} | {period}"
                )
        facts_text = "\n".join(lines)
        if len(facts_text) > 8000:
            facts_text = facts_text[:8000] + "\n... (truncated)"
        schema_block = (
            "\n\nSTRUCTURED COVERAGE FACTS (authoritative, extracted by the pipeline - "
            "use this as the complete list of coverage codes and for list, compare, "
            "count, and date questions; cite as schema-derived):\n"
            f"{facts_text}\n"
        )

    today = date.today().isoformat()
    response = llm.large_model_call(
        prompt=(
            f"{prompt}{schema_block}\n\nTODAY'S DATE: {today}\n\n"
            f"Conversation:\n{formatted_history}\n\nQuestion:\n{question}\n\n"
            f"Evidence:\n{formatted_chunks}"
        ),
        system_message="Reason only from provided evidence and structured coverage facts.",
    )
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {
            "answer": "Insufficient certified evidence to answer confidently.",
            "evidence_used": [],
            "coverage_decision": "insufficient_evidence",
            "reasoning": response,
            "confidence_factors": {
                "evidence_strength": 0.3,
                "clause_clarity": 0.3,
                "metadata_match": 0.3,
            },
        }
