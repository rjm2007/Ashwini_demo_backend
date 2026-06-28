#!/usr/bin/env python3
"""
Run the full 50-question RAG benchmark and write RAG_BENCHMARK_ANSWERS.txt.

Usage:
  python eval/run_benchmark.py
  python eval/run_benchmark.py --start Q15   # resume from question id
  python eval/run_benchmark.py --level 1     # single level only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import settings
from src.query.query_orchestrator import answer_question

EVAL_DIR = Path(__file__).parent
QUESTIONS_PATH = EVAL_DIR / "benchmark_questions.json"
# Default: ai-service/eval/ (works in Docker /app/eval/). Copy to warranty-platform/eval/ for reviewers.
OUT_PATH = EVAL_DIR / "RAG_BENCHMARK_ANSWERS.txt"


def load_benchmark() -> dict:
    return json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))


def iter_questions(data: dict, level_filter: int | None = None):
    for block in data["levels"]:
        if level_filter is not None and block["level"] != level_filter:
            continue
        for q in block["questions"]:
            yield block["level"], block["name"], q


def format_section(level: int, level_name: str) -> str:
    return (
        f"\n{'=' * 78}\n"
        f"LEVEL {level} — {level_name}\n"
        f"{'=' * 78}\n"
    )


def format_answer(
    qid: str,
    question: str,
    result: dict,
) -> str:
    evidence = result.get("evidence") or []
    pages = sorted({str(e.get("pageNumber")) for e in evidence if e.get("pageNumber") is not None})
    codes_seen: list[str] = []
    for e in evidence:
        for c in e.get("coverageCodes") or []:
            if c not in codes_seen:
                codes_seen.append(str(c))

    lines = [
        f"\n{'-' * 78}",
        f"{qid}. {question}",
        f"{'-' * 78}",
        "",
        "ANSWER:",
        result.get("answer", "(no answer)"),
        "",
        f"COVERAGE DECISION: {result.get('coverageDecision', 'n/a')}",
        f"CONFIDENCE: {result.get('confidence', 'n/a')}",
        f"INTENT: {result.get('intent', 'n/a')}",
    ]
    if pages:
        lines.append(f"EVIDENCE PAGES: {', '.join(pages)}")
    if codes_seen:
        lines.append(f"EVIDENCE CODES: {', '.join(codes_seen[:12])}")
    lines.append("")
    return "\n".join(lines)


async def run_one(question: str) -> dict:
    return await answer_question(question, [])


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", help="Resume at question id e.g. Q15")
    parser.add_argument("--level", type=int, help="Run only level 1-5")
    parser.add_argument(
        "--output",
        default=str(OUT_PATH),
        help="Output txt path (default: warranty-platform/eval/RAG_BENCHMARK_ANSWERS.txt)",
    )
    args = parser.parse_args()

    data = load_benchmark()
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    skipping = bool(args.start)
    header = [
        "=" * 78,
        data.get("title", "RAG Benchmark"),
        f"Generated (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
        "Pipeline: Phase 2 — hybrid retrieval + lexical boost + OpenAI rerank + table mode",
        f"Reranker enabled: {settings.enable_reranker}",
        f"Collection: {settings.qdrant_collection}",
        "Note: Answers reflect CERTIFIED chunks only. Compare to PDF manually.",
        "=" * 78,
    ]

    if not skipping:
        out_path.write_text("\n".join(header), encoding="utf-8")

    current_level = None
    total = 0
    done = 0

    for level, level_name, q in iter_questions(data, args.level):
        total += 1
        qid = q["id"]
        if skipping:
            if qid == args.start:
                skipping = False
            else:
                continue

        if current_level != level:
            current_level = level
            with out_path.open("a", encoding="utf-8") as f:
                f.write(format_section(level, level_name))

        print(f"Running {qid} ...", flush=True)
        try:
            result = await run_one(q["text"])
        except Exception as exc:
            result = {
                "answer": f"ERROR: {exc}",
                "coverageDecision": "error",
                "confidence": 0,
                "intent": "error",
                "evidence": [],
            }

        block = format_answer(qid, q["text"], result)
        with out_path.open("a", encoding="utf-8") as f:
            f.write(block)
        done += 1
        print(f"  done {qid} confidence={result.get('confidence')}", flush=True)

    footer = (
        f"\n{'=' * 78}\n"
        f"Completed {done}/{total} questions.\n"
        f"Output: {out_path.resolve()}\n"
    )
    with out_path.open("a", encoding="utf-8") as f:
        f.write(footer)

    print(footer)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
