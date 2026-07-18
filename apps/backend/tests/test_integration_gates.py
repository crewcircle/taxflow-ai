"""Task B10 — architectural boundary gates + boot check.

These tests codify the ports-and-adapters invariants so the decoupling can't
silently regress: vendor SDKs and raw infra SQL must live ONLY under
``src/taxflow/adapters/`` (the one place allowed to know about a concrete
vendor). They scan the source tree, so a stray ``AsyncAnthropic`` /
``sb.table(...)`` / raw ``<=>`` pgvector query reintroduced into service or
router code fails here rather than in production.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "taxflow"
ADAPTERS = SRC / "adapters"


def _py_files_outside_adapters() -> list[Path]:
    files: list[Path] = []
    for path in SRC.rglob("*.py"):
        if ADAPTERS in path.parents:
            continue
        if "__pycache__" in path.parts:
            continue
        files.append(path)
    return files


def _offending(pattern: str) -> list[str]:
    """Return "relpath:lineno" for every non-comment, non-docstring hit of
    ``pattern`` in a .py file outside the adapters package."""
    rx = re.compile(pattern)
    hits: list[str] = []
    for path in _py_files_outside_adapters():
        for i, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.lstrip()
            # skip comments and obvious docstring/prose lines (``...`` markers,
            # backtick-quoted references in module docstrings).
            if stripped.startswith("#") or stripped.startswith("*"):
                continue
            if "``" in line or line.count('"') >= 4:
                continue
            if rx.search(line):
                hits.append(f"{path.relative_to(SRC)}:{i}  {stripped}")
    return hits


@pytest.mark.parametrize(
    "pattern,label",
    [
        (r"\bAsyncAnthropic\b", "Anthropic SDK client"),
        (r"\bAsyncOpenAI\b", "OpenAI SDK client"),
        (r"\bboto3\b", "boto3 / S3 SDK"),
        (r"\bAsyncIOScheduler\b", "APScheduler engine"),
        (r"(?<![\w.])stripe\.(Webhook|checkout|Customer|Subscription)", "Stripe SDK call"),
        (r"\.rpc\(", "Supabase PostgREST rpc()"),
        (r"<=>", "raw pgvector cosine operator"),
    ],
)
def test_vendor_coupling_confined_to_adapters(pattern: str, label: str) -> None:
    offenders = _offending(pattern)
    assert not offenders, (
        f"{label} must only appear under src/taxflow/adapters/. Found:\n"
        + "\n".join(offenders)
    )


def test_no_postgrest_table_api_outside_adapters() -> None:
    """``sb.table(...)`` / ``client.table(...)`` PostgREST CRUD must be gone
    everywhere outside adapters (relational access goes through repositories)."""
    offenders = _offending(r"\b(sb|client|db|supabase)\.table\(")
    assert not offenders, (
        "Supabase PostgREST table API must not be used outside adapters:\n"
        + "\n".join(offenders)
    )


def test_raw_pool_access_confined() -> None:
    """``get_pg_conn`` (the raw psycopg2 pool) may only be imported/used by the
    db, vectorstore, repository and scheduler adapters — not services/routers."""
    allowed_suffixes = {
        "db.py",
        "ports/relational.py",  # docstring reference only
    }
    offenders = []
    for path in _py_files_outside_adapters():
        rel = str(path.relative_to(SRC))
        if rel in allowed_suffixes:
            continue
        text = path.read_text()
        if "get_pg_conn(" in text:
            offenders.append(rel)
    assert not offenders, (
        "Raw connection pool access must live in adapters/db (+ db.py). Found in:\n"
        + "\n".join(offenders)
    )


def test_app_imports_cleanly_with_default_settings() -> None:
    """Boot check: the FastAPI app + composition root import with default
    (unconfigured-R2) settings, proving the wiring graph is sound."""
    import taxflow.main  # noqa: F401
    from taxflow import providers

    # Default provider knobs resolve to the expected adapter classes.
    from taxflow.adapters.llm.litellm_adapter import LiteLLMAdapter
    from taxflow.adapters.embedding.litellm_adapter import LiteLLMEmbeddingAdapter
    from taxflow.adapters.vectorstore.pgvector import PgVectorStore

    assert isinstance(providers.get_llm(), LiteLLMAdapter)
    assert isinstance(providers.get_embedder(), LiteLLMEmbeddingAdapter)
    assert isinstance(providers.get_vector_store(), PgVectorStore)
    # Accessors are memoised (same instance twice).
    assert providers.get_llm() is providers.get_llm()
