from unittest.mock import AsyncMock, MagicMock, patch


def test_submit_query_returns_answer(client):
    fake_client = {"id": "client-1", "email": "a@b.com.au"}

    from taxflow.main import app
    from taxflow.middleware.auth import get_current_client
    from taxflow.middleware.trial_gate import check_trial_gate
    from taxflow.db import get_db
    import taxflow.routers.query as query_module

    mock_db = MagicMock()
    mock_db.queries.insert.return_value = {"id": "query-1"}

    app.dependency_overrides[get_current_client] = lambda: fake_client
    app.dependency_overrides[check_trial_gate] = lambda: fake_client
    app.dependency_overrides[get_db] = lambda: mock_db

    # Task A6: POST /query drives the compiled graph via ainvoke; the final state
    # already carries the (post-verify/corrective) answer + metadata.
    final_state = {
        "answer": "Test answer [1]",
        "citations": [{"citation": "ITAA 1997 s.8-1", "url": "", "excerpt": ""}],
        "confidence": 0.9,
        "routed_tier": "haiku",
        "verification": None,
        "caveat": None,
        "corrected_meta": None,
        "input_tokens": 10,
        "output_tokens": 10,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }

    with patch.object(
        query_module.research_graph, "ainvoke", new=AsyncMock(return_value=final_state)
    ) as mock_ainvoke, patch.object(
        query_module, "increment_usage", new_callable=AsyncMock
    ), patch.object(query_module, "embed", new_callable=AsyncMock) as mock_embed, patch.object(
        query_module.answer_cache, "get_cached_answer", new=AsyncMock(return_value=None)
    ), patch.object(
        query_module.answer_cache, "store_answer", new=AsyncMock()
    ), patch.object(
        query_module.answer_cache, "count_prior_asks", new=AsyncMock(return_value=0)
    ):
        mock_embed.return_value = [0.0] * 1536

        try:
            response = client.post("/query", json={"question": "What is the CGT discount?"})
            assert response.status_code == 200
            body = response.json()
            assert body["answer"] == "Test answer [1]"
            assert body["model_used"] == "haiku"
            # Task A4: the question is embedded once in the route and the vector is
            # passed into the graph initial state (retrieval does not re-embed).
            mock_embed.assert_awaited_once()
            mock_ainvoke.assert_awaited_once()
            initial_state = mock_ainvoke.call_args.args[0]
            assert initial_state["embedding"] == mock_embed.return_value
            assert initial_state["streaming"] is False
            assert initial_state["corrective_count"] == 0
            assert initial_state["re_retrieved"] is False
        finally:
            app.dependency_overrides.clear()


def test_submit_query_persists_corrective_metadata(client):
    """When the graph ran a corrective pass, the router persists the corrected
    (Sonnet) metadata + caveat-appended answer, and returns them (Task A6)."""
    fake_client = {"id": "client-1", "email": "a@b.com.au"}

    from taxflow.main import app
    from taxflow.middleware.auth import get_current_client
    from taxflow.middleware.trial_gate import check_trial_gate
    from taxflow.db import get_db
    import taxflow.routers.query as query_module

    captured_update = {}
    mock_db = MagicMock()
    mock_db.queries.insert.return_value = {"id": "query-1"}
    mock_db.queries.update.side_effect = lambda cid, qid, payload: captured_update.update(payload)

    app.dependency_overrides[get_current_client] = lambda: fake_client
    app.dependency_overrides[check_trial_gate] = lambda: fake_client
    app.dependency_overrides[get_db] = lambda: mock_db

    verification = {"overall_status": "needs_correction", "issues": [{"severity": "critical"}]}
    final_state = {
        "answer": "Corrected answer [1]",
        "citations": [{"citation": "y"}],
        "confidence": 0.3,  # first-pass value; corrected_meta wins for persistence
        "routed_tier": "haiku",
        "verification": verification,
        "caveat": "Caveat: review claim 1.",
        "corrected_meta": {
            "answer": "Corrected answer [1]",
            "citations": [{"citation": "y"}],
            "confidence": 0.85,
            "model_used": "sonnet",
            "input_tokens": 300,
            "output_tokens": 120,
            "cache_read_input_tokens": 200,
            "cache_creation_input_tokens": 0,
        },
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_read_input_tokens": 40,
        "cache_creation_input_tokens": 10,
    }

    with patch.object(
        query_module.research_graph, "ainvoke", new=AsyncMock(return_value=final_state)
    ), patch.object(
        query_module, "increment_usage", new_callable=AsyncMock
    ), patch.object(query_module, "embed", new=AsyncMock(return_value=[0.0] * 1536)), patch.object(
        query_module.answer_cache, "get_cached_answer", new=AsyncMock(return_value=None)
    ), patch.object(
        query_module.answer_cache, "store_answer", new=AsyncMock()
    ) as mock_store, patch.object(
        query_module.answer_cache, "count_prior_asks", new=AsyncMock(return_value=0)
    ):
        try:
            response = client.post("/query", json={"question": "risky question"})
            assert response.status_code == 200
            body = response.json()
            # Caveat appended to the stored/returned answer.
            assert body["answer"] == "Corrected answer [1]\n\nCaveat: review claim 1."
            assert body["model_used"] == "sonnet"
            assert body["confidence"] == 0.85

            # Corrective (Sonnet) metadata persisted, not the first-pass values.
            assert captured_update["model_used"] == "sonnet"
            assert captured_update["confidence_score"] == 0.85
            assert captured_update["input_tokens"] == 300
            assert captured_update["output_tokens"] == 120
            assert captured_update["cache_read_input_tokens"] == 200
            assert captured_update["verification_result"] == verification

            # A needs_correction answer must never be cached (B3 gate).
            mock_store.assert_not_awaited()
        finally:
            app.dependency_overrides.clear()


def test_submit_query_cache_hit_skips_graph(client):
    """A cache hit serves the stored answer WITHOUT invoking the graph (Task B3)."""
    fake_client = {"id": "client-1", "email": "a@b.com.au"}

    from taxflow.main import app
    from taxflow.middleware.auth import get_current_client
    from taxflow.middleware.trial_gate import check_trial_gate
    from taxflow.db import get_db
    import taxflow.routers.query as query_module

    mock_db = MagicMock()
    mock_db.queries.insert.return_value = {"id": "cached-query-1"}

    app.dependency_overrides[get_current_client] = lambda: fake_client
    app.dependency_overrides[check_trial_gate] = lambda: fake_client
    app.dependency_overrides[get_db] = lambda: mock_db

    cached = {
        "answer": "Cached answer [1]",
        "citations": [{"citation": "x"}],
        "confidence": 0.9,
        "model_used": "haiku",
    }

    ainvoke_mock = AsyncMock()
    embed_mock = AsyncMock(return_value=[0.0] * 1536)

    with patch.object(
        query_module.research_graph, "ainvoke", new=ainvoke_mock
    ), patch.object(query_module, "increment_usage", new_callable=AsyncMock), patch.object(
        query_module, "embed", new=embed_mock
    ), patch.object(
        query_module.answer_cache, "get_cached_answer", new=AsyncMock(return_value=cached)
    ), patch.object(
        query_module.answer_cache, "count_prior_asks", new=AsyncMock(return_value=0)
    ):
        try:
            response = client.post("/query", json={"question": "cached question"})
            assert response.status_code == 200
            body = response.json()
            assert body["cached"] is True
            assert body["answer"] == "Cached answer [1]"
            # No paid embed / graph work on a cache hit.
            ainvoke_mock.assert_not_awaited()
            embed_mock.assert_not_awaited()
        finally:
            app.dependency_overrides.clear()


def test_submit_query_session_id_bypasses_cache(client):
    """A session_id must bypass the answer cache read entirely (Task D3)."""
    fake_client = {"id": "client-1", "email": "a@b.com.au"}

    from taxflow.main import app
    from taxflow.middleware.auth import get_current_client
    from taxflow.middleware.trial_gate import check_trial_gate
    from taxflow.db import get_db
    import taxflow.routers.query as query_module

    mock_db = MagicMock()
    mock_db.queries.insert.return_value = {"id": "query-1"}

    app.dependency_overrides[get_current_client] = lambda: fake_client
    app.dependency_overrides[check_trial_gate] = lambda: fake_client
    app.dependency_overrides[get_db] = lambda: mock_db

    final_state = {
        "answer": "Session answer [1]",
        "citations": [{"citation": "x"}],
        "confidence": 0.9,
        "routed_tier": "haiku",
        "verification": None,
        "caveat": None,
        "corrected_meta": None,
        "input_tokens": 10,
        "output_tokens": 10,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }

    get_cache_mock = AsyncMock(return_value=None)
    store_mock = AsyncMock()

    with patch.object(
        query_module.research_graph, "ainvoke", new=AsyncMock(return_value=final_state)
    ), patch.object(query_module, "increment_usage", new_callable=AsyncMock), patch.object(
        query_module, "embed", new=AsyncMock(return_value=[0.0] * 1536)
    ), patch.object(
        query_module.answer_cache, "get_cached_answer", new=get_cache_mock
    ), patch.object(
        query_module.answer_cache, "store_answer", new=store_mock
    ), patch.object(
        query_module.answer_cache, "count_prior_asks", new=AsyncMock(return_value=0)
    ):
        try:
            response = client.post(
                "/query", json={"question": "q", "session_id": "sess-1"}
            )
            assert response.status_code == 200
            # Session-scoped: cache neither read nor written.
            get_cache_mock.assert_not_awaited()
            store_mock.assert_not_awaited()
        finally:
            app.dependency_overrides.clear()
