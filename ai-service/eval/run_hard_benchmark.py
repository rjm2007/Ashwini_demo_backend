#!/usr/bin/env python3
"""Hard benchmark: retrieval Recall@K / MRR + optional full answers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.metrics import mrr, recall_at_k
from src.query.retriever import retrieve_chunks
from src.services.warranty_code_utils import enrich_metadata_with_codes

QUESTIONS_PATH = Path(__file__).parent / "hard_benchmark_questions.json"
OUT_PATH = Path(__file__).parent.parent.parent / "eval" / "HARD_BENCHMARK_RESULTS.json"


def chunks_blob(chunks: list[dict]) -> str:
    parts = []
    for item in chunks:
        p = item.get("payload") or {}
        parts.append(p.get("chunkText") or "")
        parts.append(p.get("retrievalSnippet") or "")
        parts.append(" ".join(p.get("coverageCodes") or []))
    return " ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()

    data = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    results = []
    recalls = []

    print(f"\nHard benchmark — {len(data['questions'])} questions\n")

    for case in data["questions"]:
        q = case["text"]
        meta = enrich_metadata_with_codes({"rewritten_query": q, "semantic_keywords": []}, q)
        chunks = retrieve_chunks(q, meta, top_k=args.top_k)
        blob = chunks_blob(chunks)
        per_chunk_blobs = [chunks_blob([c]) for c in chunks]
        required = case.get("must_match_in_chunks", [])
        r_at_k = recall_at_k(required, blob, args.top_k)
        mrr_score = mrr(required, per_chunk_blobs)
        recalls.append(r_at_k)
        ok = r_at_k >= 1.0
        print(f"  [{'PASS' if ok else 'FAIL'}] {case['id']} recall@k={r_at_k:.2f} mrr={mrr_score:.2f}")
        results.append(
            {
                "id": case["id"],
                "question": q,
                "recall_at_k": r_at_k,
                "mrr": mrr_score,
                "pass": ok,
                "chunks": len(chunks),
            }
        )

    summary = {
        "mean_recall_at_k": sum(recalls) / len(recalls) if recalls else 0,
        "results": results,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nMean recall@k: {summary['mean_recall_at_k']:.2%}")
    print(f"Wrote {OUT_PATH}\n")
    return 0 if all(r["pass"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
