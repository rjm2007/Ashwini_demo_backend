#!/usr/bin/env python3
"""
RAG eval harness — measures retrieval recall on fixed warranty questions.

Usage (inside ai-service container or with PYTHONPATH=/app):
  python eval/run_eval.py
  python eval/run_eval.py --full          # also call /query/answer (slow, uses LLM)
  python eval/run_eval.py --with-metadata # run small-model metadata extraction first
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.query.retriever import retrieve_chunks
from src.services.warranty_code_utils import enrich_metadata_with_codes


def load_cases() -> list[dict]:
    path = Path(__file__).parent / "eval_questions.json"
    return json.loads(path.read_text(encoding="utf-8"))


def chunks_blob(chunks: list[dict]) -> str:
    parts = []
    for item in chunks:
        p = item.get("payload") or {}
        parts.append(p.get("chunkText") or "")
        parts.append(" ".join(p.get("coverageCodes") or []))
    return " ".join(parts).upper()


def eval_retrieval(case: dict, top_k: int, use_llm_metadata: bool) -> dict:
    question = case["question"]
    metadata: dict = {"rewritten_query": question, "semantic_keywords": []}

    if use_llm_metadata:
        from src.query.metadata_filter import extract_metadata_filters

        metadata = extract_metadata_filters(question, [])
    else:
        metadata = enrich_metadata_with_codes(metadata, question)

    chunks = retrieve_chunks(question, metadata, top_k=top_k)
    blob = chunks_blob(chunks)
    required = [s.upper() for s in case.get("must_match_in_chunks", [])]
    missing = [s for s in required if s not in blob]
    return {
        "id": case["id"],
        "pass": len(missing) == 0,
        "missing": missing,
        "codes_injected": metadata.get("warranty_codes", []),
        "top_chunks": len(chunks),
    }


def eval_full_answer(case: dict, base_url: str) -> dict:
    import urllib.request

    body = json.dumps({"question": case["question"], "conversationHistory": []}).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/query/answer",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        payload = json.loads(resp.read().decode())
    answer = (payload.get("answer") or "").upper()
    required = [s.upper() for s in case.get("must_match_in_chunks", [])]
    # Full answer: softer check — any required token in answer OR evidence
    evidence_text = " ".join(
        (e.get("chunkText") or "") for e in (payload.get("evidence") or [])
    ).upper()
    combined = answer + " " + evidence_text
    missing = [s for s in required if s not in combined]
    return {
        "id": case["id"],
        "pass": len(missing) == 0,
        "missing": missing,
        "coverage_decision": payload.get("coverageDecision"),
        "confidence": payload.get("confidence"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Warranty RAG eval")
    parser.add_argument("--full", action="store_true", help="Run full /query/answer per case")
    parser.add_argument(
        "--with-metadata",
        action="store_true",
        help="Use LLM metadata extraction (slower)",
    )
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()

    cases = load_cases()
    results: list[dict] = []

    print(f"\n{'=' * 60}")
    print(f"Warranty RAG eval — {len(cases)} cases (top_k={args.top_k})")
    print(f"{'=' * 60}\n")

    for case in cases:
        if args.full:
            result = eval_full_answer(case, args.base_url)
        else:
            result = eval_retrieval(case, args.top_k, args.with_metadata)
        results.append(result)
        status = "PASS" if result["pass"] else "FAIL"
        extra = ""
        if result.get("codes_injected"):
            extra = f" codes={result['codes_injected']}"
        if result.get("missing"):
            extra += f" missing={result['missing']}"
        print(f"  [{status}] {case['id']}: {case['question'][:55]}{extra}")

    passed = sum(1 for r in results if r["pass"])
    print(f"\n{'=' * 60}")
    print(f"Retrieval recall: {passed}/{len(results)} ({100 * passed / len(results):.0f}%)")
    print(f"{'=' * 60}\n")

    out_path = Path(__file__).parent / "eval_results.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
