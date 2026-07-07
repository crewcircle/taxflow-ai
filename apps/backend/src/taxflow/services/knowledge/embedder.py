from functools import lru_cache

from openai import AsyncOpenAI

from taxflow.config import settings

EMBEDDING_MODEL = "text-embedding-3-small"
MAX_INPUT_TOKENS = 8192


@lru_cache
def _get_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


async def embed(text: str) -> list[float]:
    response = await _get_client().embeddings.create(model=EMBEDDING_MODEL, input=text[: MAX_INPUT_TOKENS * 4])
    return response.data[0].embedding


async def embed_batch(texts: list[str]) -> list[list[float]]:
    results: list[list[float]] = []
    for i in range(0, len(texts), 100):
        batch = texts[i : i + 100]
        response = await _get_client().embeddings.create(model=EMBEDDING_MODEL, input=batch)
        results.extend(item.embedding for item in response.data)
    return results
