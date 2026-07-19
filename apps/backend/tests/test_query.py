from unittest.mock import AsyncMock, MagicMock, patch

from taxflow.routers.query import _build_final_trace


# --- A1: _build_final_trace assembly semantics -------------------------------


def test_build_final_trace_cache_hit():
    """(a) Cache hit → retrieval null, no re_retrieval, no passes block."""
    result = _build_final_trace(None, None, None)
    assert result["retrieval"] is None
    assert result["generation"] == {"model": "cache"}
    assert result["verification"] is None
    assert "re_retrieval" not in result
    assert "passes" not in result


def test_build_final_trace_verify_only_no_passes():
    """(b) Verify-only (no corrective pass) → verification.ran, no passes,
    re_retrieval omitted."""
    trace = {
        "retrieval": {"chunks_considered": 3, "candidates": []},
        "generation": {"model": "haiku", "confidence": 0.9},
    }
    verification = {"overall_status": "verified", "issues": []}
    result = _build_final_trace(trace, verification, None)
    assert result["retrieval"] == trace["retrieval"]
    assert result["generation"] == trace["generation"]
    assert result["verification"]["ran"] is True
    assert result["verification"]["status"] == "verified"
    assert "passes" not in result
    assert "re_retrieval" not in result
    assert "corrective_generation" not in result


def test_build_final_trace_corrective_and_re_retrieval():
    """(c) Corrective pass + re-retrieval → passes.changed True with DISTINCT
    first-pass vs corrected model/confidence, re_retrieval.fired True."""
    trace = {
        "retrieval": {"chunks_considered": 5, "candidates": []},
        # Top-level generation describes the FINAL (corrected) answer.
        "generation": {"model": "sonnet", "confidence": 0.85},
    }
    verification = {"overall_status": "needs_correction", "issues": [{"severity": "critical"}]}
    corrected = {"trace": {"generation": {"model": "sonnet", "confidence": 0.85}}}
    # First-pass snapshot: distinct model + confidence from the corrected pass.
    first_pass = {"model": "haiku", "confidence": 0.3}

    result = _build_final_trace(
        trace,
        verification,
        corrected,
        re_retrieved=True,
        first_pass=first_pass,
    )

    assert result["passes"]["changed"] is True
    assert result["passes"]["first_pass"] == {"model": "haiku", "confidence": 0.3}
    assert result["passes"]["corrected"] == {"model": "sonnet", "confidence": 0.85}
    # first-pass and corrected must be distinct.
    assert result["passes"]["first_pass"] != result["passes"]["corrected"]
    assert result["corrective_generation"] == corrected["trace"]["generation"]
    assert result["re_retrieval"]["fired"] is True
    # No explicit reason supplied → defaults to weak_signal.
    assert result["re_retrieval"]["reason"] == "weak_signal"
    assert result["re_retrieval"]["detail"] is None


def test_build_final_trace_re_retrieval_custom_reason():
    """A supplied re_reason/re_detail is threaded onto the re_retrieval block."""
    trace = {
        "retrieval": {"chunks_considered": 2, "candidates": []},
        "generation": {"model": "sonnet", "confidence": 0.7},
    }
    result = _build_final_trace(
        trace,
        None,
        None,
        re_retrieved=True,
        re_reason="reviewer_flag",
        re_detail="verifier flagged a gap",
    )
    assert result["re_retrieval"] == {
        "fired": True,
        "reason": "reviewer_flag",
        "detail": "verifier flagged a gap",
    }
    # A re-retrieval without a corrective pass still has no passes block.
    assert "passes" not in result


def test_build_final_trace_reviewer_flag_reason_flows_through():
    """C6: the reviewer-driven corrective widen's re_reason=="reviewer_flag" is
    threaded onto trace.re_retrieval (the inline corrective pass path)."""
    trace = {
        "retrieval": {"chunks_considered": 5, "candidates": []},
        "generation": {"model": "sonnet", "confidence": 0.85},
    }
    result = _build_final_trace(
        trace,
        {"overall_status": "needs_correction", "issues": [{"severity": "critical"}]},
        {"trace": {"generation": {"model": "sonnet", "confidence": 0.85}}},
        re_retrieved=True,
        re_reason="reviewer_flag",
        first_pass={"model": "haiku", "confidence": 0.3},
    )
    assert result["re_retrieval"]["fired"] is True
    assert result["re_retrieval"]["reason"] == "reviewer_flag"


def test_build_final_trace_preserves_firm_and_session_blocks():
    """The combiner must NOT drop the agent's additive top-level firm/session
    blocks. Includes a combined B+C firm fragment (B: firm_items/firm_items_used,
    C: profile_applied/voice_applied/usage_trend) — ALL keys must survive."""
    trace = {
        "retrieval": {"chunks_considered": 4, "candidates": []},
        "generation": {"model": "haiku", "confidence": 0.8},
        "firm": {
            # B-owned fragment.
            "firm_items": [{"citation": "Firm knowledge: memo", "cited_in_answer": True}],
            "firm_items_used": 1,
            # C-owned fragment.
            "profile_applied": True,
            "voice_applied": True,
            "profile_summary": "SMSF specialist in VIC",
            "usage_trend": {"quarter_count": 3, "prior_count": 1},
        },
        "session": {
            "prior_turns_used": 2,
            "engagement_memos_used": 1,
            "client_ref": "ACME-2026",
        },
    }
    result = _build_final_trace(trace, {"overall_status": "verified", "issues": []}, None)

    # Both additive blocks survive intact.
    assert result["firm"] == trace["firm"]
    assert result["session"] == trace["session"]
    # Every merged firm key (B + C) is preserved — neither side dropped.
    assert result["firm"]["firm_items_used"] == 1
    assert result["firm"]["firm_items"] == trace["firm"]["firm_items"]
    assert result["firm"]["profile_applied"] is True
    assert result["firm"]["usage_trend"] == {"quarter_count": 3, "prior_count": 1}
    # Top-level retrieval/generation still describe the final answer.
    assert result["retrieval"] == trace["retrieval"]
    assert result["generation"] == trace["generation"]
    assert result["verification"]["ran"] is True


def test_build_final_trace_preserves_firm_session_through_corrective_pass():
    """firm/session survive even when a corrective pass adds passes/
    corrective_generation and a re-retrieval fires."""
    trace = {
        "retrieval": {"chunks_considered": 5, "candidates": []},
        "generation": {"model": "sonnet", "confidence": 0.85},
        "firm": {"firm_items_used": 2, "profile_applied": True},
        "session": {"prior_turns_used": 1},
    }
    verification = {"overall_status": "needs_correction", "issues": [{"severity": "critical"}]}
    corrected = {"trace": {"generation": {"model": "sonnet", "confidence": 0.85}}}
    result = _build_final_trace(
        trace,
        verification,
        corrected,
        re_retrieved=True,
        re_reason="reviewer_flag",
        first_pass={"model": "haiku", "confidence": 0.3},
    )
    assert result["firm"] == {"firm_items_used": 2, "profile_applied": True}
    assert result["session"] == {"prior_turns_used": 1}
    assert result["passes"]["changed"] is True
    assert result["re_retrieval"]["fired"] is True


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
