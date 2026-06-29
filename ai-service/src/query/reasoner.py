import json
import re
from datetime import date
from pathlib import Path
from ..services.llm_service import LlmService

_BARE_CITATION_RE = re.compile(r"(?<!\[)(?<=\s)([1-9])([.,](?:\s|$))")
_CITATION_WITH_URL_RE = re.compile(r"\[(\d+)\]\(https?://[^)\s]*\)")


def _strip_citation_urls(answer: str) -> str:
    """The model occasionally attaches a fabricated/real URL to a citation
    (e.g. '[1](http://localhost:3000/documents/...)' instead of plain '[1]').
    Strip the URL, leaving just the clean bracketed citation number — the
    citation chip rendering only ever expects '[N]', nothing else."""
    return _CITATION_WITH_URL_RE.sub(lambda m: f"[{m.group(1)}]", answer)


def _fix_unbracketed_citations(answer: str, max_index: int) -> str:
    """The model is instructed to cite evidence as '[1]', '[2]' etc., but
    occasionally drops the brackets and writes a bare digit instead (e.g.
    '...100,000 miles 1.' instead of '...100,000 miles [1].'). This wraps any
    bare single digit that immediately precedes sentence-ending punctuation
    AND falls within the valid evidence-index range, leaving every other
    number in the text untouched (dollar amounts, mileage figures, years,
    multi-digit numbers, and anything not directly hugging a period/comma
    never match this pattern)."""
    if max_index <= 0:
        return answer

    def _wrap(match: "re.Match[str]") -> str:
        n = int(match.group(1))
        if 1 <= n <= max_index:
            return f"[{match.group(1)}]{match.group(2)}"
        return match.group(0)

    return _BARE_CITATION_RE.sub(_wrap, answer)


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
            wtype = fact.get("warranty_type")
            wtype_label = (
                " — NON-STANDARD (VIN-specific, layered on top of this vehicle's standard warranty)"
                if wtype == "non_standard"
                else " — STANDARD (the baseline warranty for this Make/Model/Year)"
                if wtype == "standard"
                else ""
            )
            lines.append(
                f"## Vehicle: {fact.get('vehicle') or 'Unknown vehicle'} (doc {fact.get('documentId')}){wtype_label}"
            )
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
        parsed = json.loads(response)
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
    if isinstance(parsed.get("answer"), str):
        parsed["answer"] = _strip_citation_urls(parsed["answer"])
        parsed["answer"] = _fix_unbracketed_citations(parsed["answer"], len(chunks))
    return parsed
