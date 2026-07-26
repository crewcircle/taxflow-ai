"""Step 3: index corpus/ into a local LightRAG instance (file-based storage
under lightrag_storage/, no Docker, no new DB) and answer all 30 accuracy-suite
questions in hybrid mode.

Embeddings: OpenAI text-embedding-3-small, same as production. Extraction/
generation: DeepSeek V4 Flash via OpenRouter ($0.09/$0.18 per 1M tokens,
~18x cheaper than Claude Haiku 4.5 on output) - LightRAG/Cognee are
throwaway comparison scripts (unlike baseline, which must stay on the real
ResearchAgent's actual Anthropic models to mean anything), and Anthropic
credit on this project has run out twice indexing this corpus. litellm
routes any "openrouter/<provider>/<model>" string automatically using
OPENROUTER_API_KEY from the environment - no other code path needed.

NOT run against the app's real DB in any way - working_dir is local to this
experiment directory.

Run: doppler run --project taxflow --config dev -- \\
     uv run --with lightrag-hku --with nano-vectordb \\
     python scripts/experiments/graphrag_accuracy/run_lightrag.py
"""
from __future__ import annotations

import asyncio
import os
import time

from common import CORPUS_DIR, citations_from_context, load_manifest, load_questions, save_results

import litellm

from taxflow.config import settings

WORKING_DIR = os.path.join(os.path.dirname(__file__), "lightrag_storage")

LLM_MODEL = "openrouter/deepseek/deepseek-v4-flash"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = settings.EMBEDDING_DIMENSION


async def llm_model_func(
    prompt: str,
    system_prompt: str | None = None,
    history_messages: list | None = None,
    keyword_extraction: bool = False,
    **kwargs,
) -> str:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for m in history_messages or []:
        messages.append(m)
    messages.append({"role": "user", "content": prompt})
    response = await litellm.acompletion(model=LLM_MODEL, messages=messages, max_tokens=8192)
    content = response.choices[0].message.content
    # DeepSeek (a reasoning model) sometimes returns None here - reasoning
    # tokens consumed the budget before any visible output, or content landed
    # in a different response field. Regardless of cause, LightRAG's own
    # extraction regexes crash on None ("expected string or bytes-like
    # object") rather than treating it as "no entities found" - guard so one
    # bad chunk degrades gracefully instead of failing the whole document.
    return content or ""


async def embedding_func(texts: list[str]):
    import numpy as np

    response = await litellm.aembedding(model=EMBEDDING_MODEL, input=texts)
    return np.array([item["embedding"] for item in response.data])


async def main() -> None:
    from lightrag import LightRAG, QueryParam
    from lightrag.utils import EmbeddingFunc

    os.makedirs(WORKING_DIR, exist_ok=True)
    manifest = load_manifest()
    questions = load_questions()

    print(f"Initialising LightRAG (working_dir={WORKING_DIR})...")
    rag = LightRAG(
        working_dir=WORKING_DIR,
        llm_model_func=llm_model_func,
        embedding_func=EmbeddingFunc(
            embedding_dim=EMBEDDING_DIM,
            max_token_size=8192,
            func=embedding_func,
        ),
        # First run processed documents one at a time with default (low)
        # concurrency - 14/144 docs in 44 minutes, ~7.5h projected. ainsert()
        # accepts a batch + these three concurrency knobs; passing everything
        # in ONE call lets LightRAG's own pipeline overlap documents instead
        # of fully serialising them. Already-processed docs (tracked in
        # kv_store_doc_status.json) are skipped automatically - safe to
        # re-run after the earlier partial attempt.
        max_parallel_insert=10,
        llm_model_max_async=10,
        embedding_func_max_async=10,
    )
    await rag.initialize_storages()

    print(f"Indexing {len(manifest)} documents (batched, one-time cost)...")
    texts = []
    ids = []
    for doc in manifest:
        with open(os.path.join(CORPUS_DIR, doc["filename"])) as f:
            texts.append(f.read())
        ids.append(doc["source_url"])
    await rag.ainsert(texts, ids=ids)
    print(f"Indexed {len(manifest)} documents.")

    print("\nAnswering accuracy-suite questions (mode=hybrid)...")
    results = []
    for q in questions:
        start = time.monotonic()
        answer = await rag.aquery(q["question"], param=QueryParam(mode="hybrid"))
        elapsed_ms = (time.monotonic() - start) * 1000
        results.append(
            {
                "id": q["id"],
                "answer": answer,
                "citations": citations_from_context(answer, manifest),
                "wall_ms": round(elapsed_ms),
            }
        )
        print(f"  [{q['id']}] -> {elapsed_ms:.0f}ms")

    save_results("lightrag", results)


if __name__ == "__main__":
    asyncio.run(main())
