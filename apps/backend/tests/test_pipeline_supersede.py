from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taxflow.services.knowledge import pipeline


def test_mark_superseded_delegates_to_repo_and_returns_count():
    repos = MagicMock()
    repos.knowledge_ingest.mark_superseded.return_value = 3

    with patch("taxflow.services.knowledge.pipeline.get_relational_data", return_value=repos):
        result = pipeline._mark_superseded({"TR 2020/4": "TR 2024/1", "TD 2019/1": "TR 2024/1"})

    assert result == 3
    mapping = repos.knowledge_ingest.mark_superseded.call_args.args[0]
    assert mapping == {"TR 2020/4": "TR 2024/1", "TD 2019/1": "TR 2024/1"}


def test_mark_superseded_empty_mapping_delegates_and_returns_zero():
    # The repo itself short-circuits an empty mapping (returns 0 without a DB call);
    # the pipeline just delegates.
    repos = MagicMock()
    repos.knowledge_ingest.mark_superseded.return_value = 0

    with patch("taxflow.services.knowledge.pipeline.get_relational_data", return_value=repos):
        result = pipeline._mark_superseded({})

    assert result == 0


@pytest.mark.asyncio
async def test_process_document_maps_superseded_to_ingested_citation():
    # process_document should map each superseded citation -> the citation of the
    # document being ingested (the superseding, current one).
    metadata = {
        "source_type": "ato_ruling",
        "url": "https://example.test/tr-2024-1",
        "citation": "TR 2024/1",
        "title": "New ruling",
        "jurisdiction": "federal",
    }
    text = "This ruling replaces TR 2020/4 and TD 2019/1."

    captured = {}

    def fake_mark(mapping):
        captured["mapping"] = mapping
        return len(mapping)

    with patch("taxflow.services.knowledge.pipeline.chunk_text", return_value=["chunk"]), \
         patch("taxflow.services.knowledge.pipeline.embed_batch", new=AsyncMock(return_value=[[0.0]])), \
         patch("taxflow.services.knowledge.pipeline._upsert_chunks", return_value=1), \
         patch("taxflow.services.knowledge.pipeline.classify_topic", return_value=None), \
         patch(
             "taxflow.services.knowledge.pipeline._detect_superseded_citations",
             return_value={"TR 2020/4", "TD 2019/1", "TR 2024/1"},
         ), \
         patch("taxflow.services.knowledge.pipeline._mark_superseded", side_effect=fake_mark):
        await pipeline.process_document(text, metadata)

    mapping = captured["mapping"]
    # The ingested doc's own citation must be excluded from the keys...
    assert "TR 2024/1" not in mapping
    assert set(mapping.keys()) == {"TR 2020/4", "TD 2019/1"}
    # ...and every mapping VALUE must equal the ingested doc's citation.
    assert all(v == metadata["citation"] for v in mapping.values())
