from unittest.mock import MagicMock, patch

from taxflow.services.knowledge import pipeline


def test_mark_superseded_delegates_to_repo_and_returns_count():
    repos = MagicMock()
    repos.knowledge_ingest.mark_superseded.return_value = 3

    with patch("taxflow.services.knowledge.pipeline.get_relational_data", return_value=repos):
        result = pipeline._mark_superseded({"TR 2020/4", "TD 2019/1"})

    assert result == 3
    citations = repos.knowledge_ingest.mark_superseded.call_args.args[0]
    assert set(citations) == {"TR 2020/4", "TD 2019/1"}


def test_mark_superseded_empty_set_delegates_and_returns_zero():
    # The repo itself short-circuits an empty set (returns 0 without a DB call);
    # the pipeline just delegates.
    repos = MagicMock()
    repos.knowledge_ingest.mark_superseded.return_value = 0

    with patch("taxflow.services.knowledge.pipeline.get_relational_data", return_value=repos):
        result = pipeline._mark_superseded(set())

    assert result == 0
