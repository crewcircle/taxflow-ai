from unittest.mock import AsyncMock, MagicMock, patch


def test_submit_query_returns_answer(client):
    fake_client = {"id": "client-1", "email": "a@b.com.au"}

    from taxflow.main import app
    from taxflow.middleware.auth import get_current_client
    from taxflow.middleware.trial_gate import check_trial_gate
    from taxflow.db import get_db
    import taxflow.routers.query as query_module

    mock_db = MagicMock()
    mock_db.table.return_value.insert.return_value.execute.return_value.data = [{"id": "query-1"}]

    app.dependency_overrides[get_current_client] = lambda: fake_client
    app.dependency_overrides[check_trial_gate] = lambda: fake_client
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch.object(query_module, "agent") as mock_agent, patch.object(
        query_module, "increment_usage", new_callable=AsyncMock
    ), patch.object(query_module, "embed", new_callable=AsyncMock) as mock_embed, patch.object(
        query_module.answer_cache, "get_cached_answer", new=AsyncMock(return_value=None)
    ), patch.object(
        query_module.answer_cache, "store_answer", new=AsyncMock()
    ), patch.object(
        query_module.verify_mod, "should_verify", return_value=False
    ):
        mock_embed.return_value = [0.0] * 1536
        mock_agent.run = AsyncMock(
            return_value={
                "answer": "Test answer [1]",
                "citations": [{"citation": "ITAA 1997 s.8-1", "url": "", "excerpt": ""}],
                "confidence": 0.9,
                "model_used": "haiku",
                "chunks_retrieved": 1,
                "input_tokens": 10,
                "output_tokens": 10,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            }
        )

        try:
            response = client.post("/query", json={"question": "What is the CGT discount?"})
            assert response.status_code == 200
            body = response.json()
            assert body["answer"] == "Test answer [1]"
            assert body["model_used"] == "haiku"
            # Task A4: the question is embedded once in the route and the vector is
            # passed down to agent.run (so retrieval does not re-embed).
            mock_embed.assert_awaited_once()
            _, run_kwargs = mock_agent.run.call_args
            assert run_kwargs["embedding"] == mock_embed.return_value
        finally:
            app.dependency_overrides.clear()
