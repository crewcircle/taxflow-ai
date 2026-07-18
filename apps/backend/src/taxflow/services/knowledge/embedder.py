import asyncio
from functools import lru_cache

from openai import AsyncOpenAI, RateLimitError

from taxflow.config import settings

EMBEDDING_MODEL = "text-embedding-3-small"
MAX_INPUT_TOKENS = 8192


@lru_cache
def _get_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


async def _create_with_retry(input_):
    """Retry on 429s with backoff. Large ingest runs (a whole Act's worth of
    chunks, hundreds of batches back to back) can burst past the account's
    tokens-per-minute limit even though any single batch is well within it -
    this was previously uncaught and aborted the whole ingest partway through.
    """
    for attempt in range(5):
        try:
            return await _get_client().embeddings.create(model=EMBEDDING_MODEL, input=input_)
        except RateLimitError:
            if attempt == 4:
                raise
            await asyncio.sleep(2**attempt)
    raise AssertionError("unreachable")


async def embed(text: str) -> list[float]:
    response = await _create_with_retry(text[: MAX_INPUT_TOKENS * 4])
    return response.data[0].embedding


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """chunk_text() splits on sentence boundaries, so a chunk normally stays
    well under MAX_INPUT_TOKENS - but source text with no sentence-ending
    punctuation for a long stretch (e.g. a table dumped as one DOCX paragraph)
    can produce one oversized "chunk" the splitter had no boundary to break
    on. embed() already guards against this with the same char-per-token
    proxy truncation; embed_batch() didn't, so one bad chunk raised a 400 and
    aborted every chunk after it in the batch."""
    results: list[list[float]] = []
    for i in range(0, len(texts), 100):
        batch = [t[: MAX_INPUT_TOKENS * 4] for t in texts[i : i + 100]]
        response = await _create_with_retry(batch)
        results.extend(item.embedding for item in response.data)
    return results
