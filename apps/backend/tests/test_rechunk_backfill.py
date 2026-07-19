"""Task C4: re-chunk / re-embed backfill (offline).

No DB / LLM / network. The repo delegations are asserted against a fake conn
(like test_repositories.py); the scraper resolver is a pure function; the
orchestration runs on fakes/mocks (scraper registry, fetch_document_content,
embed_batch, _upsert_chunks patched).
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Make scripts/ importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import rechunk_backfill  # noqa: E402

from taxflow.adapters.db import repositories  # noqa: E402
from taxflow.adapters.db.repositories import KnowledgeIngestRepo  # noqa: E402


# --- fake conn (mirrors test_repositories.py) --------------------------------
class _FakeCursor:
    def __init__(self, fetchall=None, rowcount=0):
        self.executed = []
        self._fetchall = fetchall or []
        self.rowcount = rowcount

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self._fetchall

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self, *args, **kwargs):
        return self._cursor

    def commit(self):
        self.committed = True


@contextmanager
def _fake_pool(cursor):
    yield _FakeConn(cursor)


def _patch_conn(cursor):
    return patch.object(repositories, "get_pg_conn", lambda: _fake_pool(cursor))


# --- repo delegation ---------------------------------------------------------
def test_delete_by_source_url_issues_delete():
    cur = _FakeCursor(rowcount=7)
    with _patch_conn(cur):
        result = KnowledgeIngestRepo().delete_by_source_url("http://x")
    assert result == 7
    sql, params = cur.executed[0]
    assert "DELETE FROM knowledge_chunks" in sql
    assert "source_url = %s" in sql
    assert params == ("http://x",)


def test_list_ingested_sources_issues_select():
    rows = [{"source_url": "http://x", "source_type": "legislation"}]
    cur = _FakeCursor(fetchall=rows)
    with _patch_conn(cur):
        result = KnowledgeIngestRepo().list_ingested_sources()
    assert result == rows
    sql = cur.executed[0][0]
    assert "SELECT" in sql
    assert "FROM knowledge_chunks" in sql
    assert "source_url" in sql
    assert "GROUP BY source_url" in sql


# --- scraper resolver --------------------------------------------------------
@pytest.mark.parametrize(
    "url,source_type,expected",
    [
        ("https://www.ato.gov.au/law/view/pdf/pbr/tr2024-001.pdf", "ato_ruling", "ATORulingsScraper"),
        ("https://www.legislation.gov.au/C2024/latest/text", "legislation", "LegislationScraper"),
        ("https://www.austlii.edu.au/cgi-bin/viewdoc/au/cases/cth/FCA/2024/1.html", "court_decision", "AustLIIScraper"),
        ("https://www.revenue.nsw.gov.au/about/legislation-and-rulings/revenue-rulings/rulings/pta/pta001", "state_ruling", "StateRevenueScraper[NSW]"),
        ("https://www.sro.vic.gov.au/about-us/laws-legal-cases-and-rulings/public-rulings/x", "state_ruling", "StateRevenueScraper[VIC]"),
        ("https://treasury.nt.gov.au/foo/bar.pdf", "state_ruling", "StateRevenueScraper[NT]"),
    ],
)
def test_resolver_returns_expected_scraper(url, source_type, expected):
    assert rechunk_backfill.resolve_scraper_name(url, source_type) == expected


def test_resolver_source_type_fallback_when_host_unknown():
    # Unknown host but known source_type -> falls back to source_type rule.
    assert (
        rechunk_backfill.resolve_scraper_name("https://unknown.example/doc", "ato_ruling")
        == "ATORulingsScraper"
    )


def test_resolver_returns_none_for_unknown():
    assert rechunk_backfill.resolve_scraper_name("https://random.example/x", None) is None
    assert rechunk_backfill.resolve_scraper_name("https://random.example/x", "mystery") is None
    assert rechunk_backfill.resolve_scraper_name(None, None) is None


def test_resolve_scraper_instance_from_registry():
    factory = MagicMock(return_value="scraper-instance")
    registry = [("ATORulingsScraper", factory)]
    inst = rechunk_backfill.resolve_scraper(
        "https://www.ato.gov.au/x.pdf", "ato_ruling", registry
    )
    assert inst == "scraper-instance"
    factory.assert_called_once()


def test_resolve_scraper_none_when_not_in_registry():
    # Resolves to a name, but that name is absent from the (empty) registry.
    inst = rechunk_backfill.resolve_scraper(
        "https://www.ato.gov.au/x.pdf", "ato_ruling", []
    )
    assert inst is None


# --- orchestration -----------------------------------------------------------
@pytest.mark.asyncio
async def test_backfill_source_calls_resolve_fetch_delete_reingest():
    row = {
        "source_url": "https://www.ato.gov.au/law/view/pdf/pbr/tr2024-001.pdf",
        "source_type": "ato_ruling",
        "title": "TR 2024/1",
        "citation": "TR 2024/1",
        "effective_date": None,
        "jurisdiction": "federal",
        "source_object_key": "objkey",
    }
    scraper = MagicMock()
    scraper.fetch_document_content = AsyncMock(return_value="X" * 500)
    scraper.aclose = AsyncMock()
    factory = MagicMock(return_value=scraper)
    registry = [("ATORulingsScraper", factory)]

    repo = MagicMock()
    repo.delete_by_source_url.return_value = 3

    captured = {}

    async def fake_process(text, metadata, source_object_key=None):
        captured["text"] = text
        captured["metadata"] = metadata
        captured["source_object_key"] = source_object_key
        return 9

    with patch(
        "rechunk_backfill.process_document", new=fake_process
    ):
        status = await rechunk_backfill.backfill_source(
            row, registry, repo, dry_run=False
        )

    scraper.fetch_document_content.assert_awaited_once_with(row["source_url"])
    repo.delete_by_source_url.assert_called_once_with(row["source_url"])
    # Metadata rebuilt from the row (source_url -> url).
    assert captured["metadata"]["url"] == row["source_url"]
    assert captured["metadata"]["citation"] == "TR 2024/1"
    assert captured["source_object_key"] == "objkey"
    assert "OK" in status


@pytest.mark.asyncio
async def test_backfill_source_skips_unmatched_scraper():
    row = {"source_url": "https://random.example/x", "source_type": "mystery"}
    repo = MagicMock()
    status = await rechunk_backfill.backfill_source(row, [], repo, dry_run=False)
    assert "SKIP" in status
    repo.delete_by_source_url.assert_not_called()


@pytest.mark.asyncio
async def test_backfill_source_dry_run_does_not_delete_or_reingest():
    row = {
        "source_url": "https://www.ato.gov.au/x.pdf",
        "source_type": "ato_ruling",
    }
    scraper = MagicMock()
    scraper.fetch_document_content = AsyncMock(return_value="Y" * 500)
    scraper.aclose = AsyncMock()
    registry = [("ATORulingsScraper", MagicMock(return_value=scraper))]
    repo = MagicMock()

    with patch(
        "rechunk_backfill.process_document",
        new=AsyncMock(return_value=0),
    ) as pdoc:
        status = await rechunk_backfill.backfill_source(
            row, registry, repo, dry_run=True
        )

    assert "DRY-RUN" in status
    repo.delete_by_source_url.assert_not_called()
    pdoc.assert_not_called()


@pytest.mark.asyncio
async def test_run_backfill_iterates_sources_with_limit(monkeypatch):
    from taxflow.config import settings

    # run_backfill flips HIERARCHICAL_CHUNKING_ENABLED on; keep it from leaking
    # into other tests in the same process.
    monkeypatch.setattr(settings, "HIERARCHICAL_CHUNKING_ENABLED", False)
    sources = [
        {"source_url": "https://www.ato.gov.au/a.pdf", "source_type": "ato_ruling"},
        {"source_url": "https://www.ato.gov.au/b.pdf", "source_type": "ato_ruling"},
        {"source_url": "https://www.ato.gov.au/c.pdf", "source_type": "ato_ruling"},
    ]
    repo = MagicMock()
    repo.list_ingested_sources.return_value = sources
    rel = MagicMock()
    rel.knowledge_ingest = repo

    calls = []

    async def fake_backfill_source(row, registry, r, *, dry_run):
        calls.append(row["source_url"])
        return "OK"

    with patch("rechunk_backfill.get_relational_data", return_value=rel), patch(
        "rechunk_backfill.get_scraper_registry", return_value=[]
    ), patch.object(rechunk_backfill, "backfill_source", new=fake_backfill_source):
        await rechunk_backfill.run_backfill(limit=2, dry_run=True, source=None)

    assert calls == [
        "https://www.ato.gov.au/a.pdf",
        "https://www.ato.gov.au/b.pdf",
    ]
