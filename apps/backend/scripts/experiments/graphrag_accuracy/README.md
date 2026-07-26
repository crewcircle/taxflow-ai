# Graph-RAG accuracy experiment (LightRAG vs Cognee vs baseline)

Disposable, standalone comparison harness. Does NOT touch production code,
schema, or dependencies — `lightrag-hku` and `cognee` are installed only into
this experiment's own throwaway environment (`uv run --with ...`), never added
to `pyproject.toml`. Every step writes only under this directory (`corpus/`,
`lightrag_storage/`, `cognee_storage/`, `results/`) plus one read-only SELECT
against the real `knowledge_chunks` table.

## Why this exists

TaxFlow's global (non-firm-specific) tax knowledge base is "ground truth" -
legislation, rulings, case law - and it's structurally a graph (sections
reference other sections, get amended, have interacting regimes). The
hypothesis: a real knowledge-graph layer over just that global tier could
improve retrieval quality (finding *structurally* related provisions a pure
embedding search misses) and explainability (a visible reasoning path instead
of a similarity score). Firm/engagement tiers are NOT touched - they're
interpretation/context, not facts, so they stay on the existing pgvector path
unchanged regardless of what this experiment finds.

## Steps

```bash
cd apps/backend

# 1. Pull the relevant subset of the real knowledge base (read-only, prod DB)
#    and reconstruct full documents from knowledge_chunks rows into corpus/.
doppler run --project taxflow --config prd -- \
    uv run python scripts/experiments/graphrag_accuracy/extract_corpus.py

# 2. Run the EXISTING pipeline (ResearchAgent, unmodified) as the baseline.
#    MUST be --config prd - --config dev's DB is the throwaway integration-test
#    Postgres and has ZERO knowledge_chunks rows, which silently produces
#    "no source documents were provided" for every question instead of an error.
doppler run --project taxflow --config prd -- \
    uv run python scripts/experiments/graphrag_accuracy/run_baseline.py

# 3. Index corpus/ into a local LightRAG instance and answer all 30 questions.
#    Requires OPENROUTER_API_KEY (set once: `doppler secrets set
#    OPENROUTER_API_KEY --project taxflow --config dev`) - extraction runs on
#    DeepSeek V4 Flash via OpenRouter, not Anthropic (see run_lightrag.py's
#    docstring for why).
doppler run --project taxflow --config dev -- \
    uv run --with lightrag-hku --with nano-vectordb \
    python scripts/experiments/graphrag_accuracy/run_lightrag.py

# 4. Index corpus/ into a local Cognee instance (SQLite+Kuzu+LanceDB, all
#    embedded/local, no Docker) and answer all 30 questions. Same
#    OPENROUTER_API_KEY requirement as step 3.
doppler run --project taxflow --config dev -- \
    uv run --with cognee \
    python scripts/experiments/graphrag_accuracy/run_cognee.py

# 5. Score all three result sets with the SAME score_answer() heuristic the
#    real accuracy suite uses, and print/save a comparison report.
uv run python scripts/experiments/graphrag_accuracy/compare.py
```

## Cost / scope guardrails

- Corpus is scoped to documents actually relevant to the 30 accuracy-suite
  questions (union of what the current pipeline retrieves for each question,
  plus anything matching an `expected_citations` label) - NOT the full
  615-document knowledge base. Keeps LLM extraction cost bounded to roughly
  the same order of magnitude as one accuracy-suite run.
- Indexing (LightRAG's entity extraction, Cognee's cognify) is a ONE-TIME
  cost per library, not per question. Re-running `compare.py` alone is free.
- Embeddings reuse the app's existing `OPENAI_API_KEY` (via doppler).
  Extraction/generation for LightRAG and Cognee runs on DeepSeek V4 Flash via
  OpenRouter ($0.09/$0.18 per 1M tokens - roughly 18x cheaper than Claude
  Haiku 4.5 on output) rather than Anthropic: baseline must stay on the real
  ResearchAgent's actual Anthropic models to mean anything, but LightRAG/
  Cognee are throwaway comparison scripts where the vendor answering doesn't
  affect what's being tested ("does graph-RAG help"), and Anthropic credit on
  this project ran out twice indexing this corpus. Requires
  `OPENROUTER_API_KEY` (`doppler secrets set OPENROUTER_API_KEY --project
  taxflow --config dev`, run once, key never touches chat/code).

## Reading the results

`results/comparison.md` after step 5: per-question and aggregate pass rate
(>=4/5, matching the real suite's PASS bar) for baseline / LightRAG / Cognee,
plus wall-clock time per pipeline. This is a directional signal for a go/no-go
decision, not a production benchmark - see the caveats in the top-level
research writeup this experiment came out of.
