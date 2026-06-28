# RAG eval harness

Measures **retrieval recall** on fixed warranty questions against **certified** Qdrant chunks.

## Run

```bash
# Inside the ai-service container (recommended)
docker exec warranty-ai-service python eval/run_eval.py

# With LLM metadata extraction (slower)
docker exec warranty-ai-service python eval/run_eval.py --with-metadata

# Full pipeline (answer + evidence, uses OpenAI)
docker exec warranty-ai-service python eval/run_eval.py --full
```

Requires at least one **certified** document in Qdrant. Results are written to `eval/eval_results.json`.

## Phase 2 (production)

- OpenAI reranker on top 20 hybrid candidates (`ENABLE_RERANKER=true`)
- Table/list reasoning mode for filter and comparison questions
- `run_benchmark.py` — full 50-question suite → `RAG_BENCHMARK_ANSWERS.txt`

```bash
docker exec warranty-ai-service python eval/run_benchmark.py
docker cp warranty-ai-service:/app/eval/RAG_BENCHMARK_ANSWERS.txt ../eval/
```

## Phase 1 retrieval improvements (production)

- `warranty_code_utils.py` — regex codes + symptom hints + aliases (e.g. EPA17 → GHG/emission)
- `retrieval_utils.rerank_with_lexical_boost` — promotes chunks matching codes/keywords
- `fetch_k` increased to 50 for hybrid prefetch
- Stricter code-listing rules in `final_reasoning.txt`
