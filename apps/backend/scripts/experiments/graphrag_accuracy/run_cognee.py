"""Step 4: index corpus/ into a local Cognee instance (SQLite + embedded Kuzu
graph + embedded LanceDB vectors - all local files, no Docker, no external
service) and answer all 30 accuracy-suite questions via GRAPH_COMPLETION.

Embeddings: OpenAI text-embedding-3-small, same as production. Extraction/
generation (cognify calls the LLM TWICE per chunk - graph extraction +
summarization): DeepSeek V4 Flash via OpenRouter ($0.09/$0.18 per 1M
tokens) rather than Anthropic - Cognee/LightRAG are throwaway comparison
scripts (unlike baseline, which must stay on the real ResearchAgent's
actual Anthropic models to mean anything), and Anthropic credit on this
project has run out twice indexing this corpus. Cognee's LLMConfig routes
ANY OpenAI-compatible endpoint via llm_provider="openai" + a custom
llm_endpoint - the same convention litellm itself uses for third-party
OpenAI-compatible APIs, which is exactly what OpenRouter is. Requires
OPENROUTER_API_KEY to already be set (e.g. via `doppler secrets set
OPENROUTER_API_KEY --project taxflow --config dev`, run once outside this
script so the key never has to appear in chat/code).

Env vars must be set BEFORE `import cognee` (its config is read at import
time), which is why this file sets os.environ first and does the cognee
import inside main() rather than at module load.

Run: doppler run --project taxflow --config dev -- \\
     uv run --with cognee \\
     python scripts/experiments/graphrag_accuracy/run_cognee.py
"""
from __future__ import annotations

import asyncio
import os
import time

import common  # noqa: F401 - side effect: puts src/ and backend root on sys.path

HERE = os.path.dirname(__file__)
STORAGE_DIR = os.path.join(HERE, "cognee_storage")
DATASET_NAME = "taxflow_experiment"


def _configure_env() -> None:
    from taxflow.config import settings

    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if not openrouter_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY not set - run "
            "`doppler secrets set OPENROUTER_API_KEY --project taxflow --config dev` first."
        )
    os.environ.setdefault("LLM_API_KEY", openrouter_key)
    os.environ.setdefault("LLM_PROVIDER", "openai")
    os.environ.setdefault("LLM_MODEL", "openai/deepseek/deepseek-v4-flash")
    os.environ.setdefault("LLM_ENDPOINT", "https://openrouter.ai/api/v1")
    os.environ.setdefault("EMBEDDING_API_KEY", settings.OPENAI_API_KEY)
    os.environ.setdefault("EMBEDDING_PROVIDER", "openai")
    os.environ.setdefault("EMBEDDING_MODEL", "openai/text-embedding-3-small")
    os.environ.setdefault("EMBEDDING_DIMENSIONS", str(settings.EMBEDDING_DIMENSION))
    # Local-only storage, isolated to this experiment directory (never the
    # app's real Postgres/R2 - Cognee's defaults are already file-based:
    # DB_PROVIDER=sqlite, GRAPH_DATABASE_PROVIDER=kuzu, VECTOR_DB_PROVIDER=lancedb).
    os.makedirs(STORAGE_DIR, exist_ok=True)
    os.environ.setdefault("DATA_ROOT_DIRECTORY", os.path.join(STORAGE_DIR, "data"))
    os.environ.setdefault("SYSTEM_ROOT_DIRECTORY", os.path.join(STORAGE_DIR, "system"))


async def main() -> None:
    _configure_env()

    import cognee

    from common import CORPUS_DIR, citations_from_context, load_manifest, load_questions, save_results  # noqa: PLC0415

    manifest = load_manifest()
    questions = load_questions()

    print(f"Adding {len(manifest)} documents to dataset '{DATASET_NAME}'...")
    for i, doc in enumerate(manifest, 1):
        with open(os.path.join(CORPUS_DIR, doc["filename"])) as f:
            text = f.read()
        await cognee.add(text, dataset_name=DATASET_NAME)
        print(f"  [{i}/{len(manifest)}] added {doc['citation']}")

    print("\nRunning cognify (one-time graph-extraction cost)...")
    await cognee.cognify(datasets=[DATASET_NAME])

    print("\nAnswering accuracy-suite questions (GRAPH_COMPLETION)...")
    results = []
    for q in questions:
        start = time.monotonic()
        hits = await cognee.search(
            query_text=q["question"],
            query_type=cognee.SearchType.GRAPH_COMPLETION,
            datasets=[DATASET_NAME],
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        # cognee.search returns a list; GRAPH_COMPLETION's answer is typically
        # the first (only) item, as plain text.
        answer = hits[0] if hits else ""
        answer_text = answer if isinstance(answer, str) else str(answer)
        results.append(
            {
                "id": q["id"],
                "answer": answer_text,
                "citations": citations_from_context(answer_text, manifest),
                "wall_ms": round(elapsed_ms),
            }
        )
        print(f"  [{q['id']}] -> {elapsed_ms:.0f}ms")

    save_results("cognee", results)


if __name__ == "__main__":
    asyncio.run(main())
