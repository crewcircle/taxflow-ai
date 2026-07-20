"""Phase 2: engagements + firm-clients API and attribution-wiring tests.

Follows the ``test_annotations_api.py`` / ``test_feedback_and_stream.py`` style:
FastAPI ``TestClient`` + ``app.dependency_overrides`` with a ``MagicMock`` db.
``client_id`` is always forced from the auth context, so the mocks assert the
scoped repo calls rather than any body-supplied client id.
"""
from unittest.mock import MagicMock

import pytest
from unittest.mock import AsyncMock, patch

from taxflow.main import app
from taxflow.middleware.auth import get_current_client
from taxflow.middleware.trial_gate import check_trial_gate
from taxflow.db import get_db


CLIENT = {"id": "client-1", "email": "a@b.com.au"}


def _override(fake_client, mock_db):
    app.dependency_overrides[get_current_client] = lambda: fake_client
    app.dependency_overrides[check_trial_gate] = lambda: fake_client
    app.dependency_overrides[get_db] = lambda: mock_db


# --- POST /engagements: default description + verbatim description -----------


def test_create_engagement_applies_default_when_description_blank(client):
    mock_db = MagicMock()
    mock_db.engagements.create.return_value = {
        "id": "eng-1",
        "engagement_number": 1,
        "description": "General tax research — 2026-07-20",
    }
    _override(CLIENT, mock_db)
    try:
        resp = client.post("/engagements", json={"firm_client_id": "fc-1"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["engagement_number"] == 1
        # The description passed to the repo is the app-layer default (non-empty).
        args = mock_db.engagements.create.call_args.args
        # (client_id, firm_client_id, description, created_by)
        assert args[0] == "client-1"
        assert args[1] == "fc-1"
        assert args[2].startswith("General tax research — ")
    finally:
        app.dependency_overrides.clear()


def test_create_engagement_stores_description_verbatim(client):
    mock_db = MagicMock()
    mock_db.engagements.create.return_value = {
        "id": "eng-2",
        "engagement_number": 2,
        "description": "FY24 R&D tax incentive",
    }
    _override(CLIENT, mock_db)
    try:
        resp = client.post(
            "/engagements",
            json={"firm_client_id": "fc-1", "description": "FY24 R&D tax incentive"},
        )
        assert resp.status_code == 201
        assert resp.json()["engagement_number"] == 2
        args = mock_db.engagements.create.call_args.args
        assert args[2] == "FY24 R&D tax incentive"
    finally:
        app.dependency_overrides.clear()


def test_create_engagement_preserves_surrounding_whitespace(client):
    """R3 contract: a non-blank description is stored verbatim — surrounding
    whitespace must NOT be trimmed (default only applies when blank)."""
    mock_db = MagicMock()
    mock_db.engagements.create.return_value = {"id": "eng-3", "engagement_number": 3}
    _override(CLIENT, mock_db)
    try:
        resp = client.post(
            "/engagements",
            json={"firm_client_id": "fc-1", "description": "  FY24 R&D  "},
        )
        assert resp.status_code == 201
        args = mock_db.engagements.create.call_args.args
        assert args[2] == "  FY24 R&D  "
    finally:
        app.dependency_overrides.clear()


def test_create_engagement_whitespace_only_uses_default(client):
    """A whitespace-only description is treated as blank → dated default."""
    mock_db = MagicMock()
    mock_db.engagements.create.return_value = {"id": "eng-4", "engagement_number": 4}
    _override(CLIENT, mock_db)
    try:
        resp = client.post(
            "/engagements", json={"firm_client_id": "fc-1", "description": "   "}
        )
        assert resp.status_code == 201
        args = mock_db.engagements.create.call_args.args
        assert args[2].startswith("General tax research — ")
    finally:
        app.dependency_overrides.clear()


def test_create_engagement_foreign_firm_client_is_404(client):
    # The repo raises ValueError when the firm-client is unknown / another
    # tenant's; the router maps that to 404 so a caller cannot probe.
    mock_db = MagicMock()
    mock_db.engagements.create.side_effect = ValueError("firm_client not found")
    _override(CLIENT, mock_db)
    try:
        resp = client.post("/engagements", json={"firm_client_id": "foreign-fc"})
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


# --- GET /engagements list + filters + GET /{id} 404 -------------------------


def test_list_engagements_passes_filters_through(client):
    mock_db = MagicMock()
    mock_db.engagements.list_for_client.return_value = []
    _override(CLIENT, mock_db)
    try:
        resp = client.get(
            "/engagements", params={"firm_client_id": "fc-1", "status": "active"}
        )
        assert resp.status_code == 200
        mock_db.engagements.list_for_client.assert_called_once_with(
            "client-1", "fc-1", "active"
        )
    finally:
        app.dependency_overrides.clear()


def test_get_engagement_404_when_repo_returns_none(client):
    mock_db = MagicMock()
    mock_db.engagements.get_for_client.return_value = None
    _override(CLIENT, mock_db)
    try:
        resp = client.get("/engagements/eng-9")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_get_engagement_returns_owned_row(client):
    mock_db = MagicMock()
    mock_db.engagements.get_for_client.return_value = {"id": "eng-1", "engagement_number": 1}
    _override(CLIENT, mock_db)
    try:
        resp = client.get("/engagements/eng-1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "eng-1"
        mock_db.engagements.get_for_client.assert_called_once_with("client-1", "eng-1")
    finally:
        app.dependency_overrides.clear()


# --- POST /firm-clients returns {id, name} -----------------------------------


def test_create_firm_client_returns_id_and_name(client):
    mock_db = MagicMock()
    mock_db.firm_clients.create.return_value = {"id": "fc-1", "name": "Acme Pty Ltd"}
    _override(CLIENT, mock_db)
    try:
        resp = client.post("/firm-clients", json={"name": "Acme Pty Ltd"})
        assert resp.status_code == 201
        assert resp.json() == {"id": "fc-1", "name": "Acme Pty Ltd"}
        mock_db.firm_clients.create.assert_called_once_with("client-1", "Acme Pty Ltd")
    finally:
        app.dependency_overrides.clear()


def test_create_firm_client_rejects_blank_name(client):
    mock_db = MagicMock()
    _override(CLIENT, mock_db)
    try:
        resp = client.post("/firm-clients", json={"name": "   "})
        assert resp.status_code == 422
        mock_db.firm_clients.create.assert_not_called()
    finally:
        app.dependency_overrides.clear()


# --- ATO upload attribution regression (Phase 2 fix) -------------------------


def test_ato_upload_persists_engagement_id_and_client_ref(client, monkeypatch):
    """Regression lock: the ATO upload previously inserted the document with NO
    client_ref/engagement_id. It must now persist BOTH on the inserted row."""
    import taxflow.routers.ato_response as ato

    async def _fake_classify(self, text):
        return {"letter_type": "audit", "deadline_days": 28}

    async def _fake_draft(self, **kwargs):
        return {"response_letter": "Dear ATO, ..."}

    monkeypatch.setattr(ato, "_extract_text", lambda b: "letter text")
    monkeypatch.setattr(ato.ATOLetterClassifier, "classify", _fake_classify)
    monkeypatch.setattr(ato.ATOResponseDrafter, "draft", _fake_draft)
    monkeypatch.setattr(ato, "get_handler", lambda lt: type("H", (), {"get_strategy": lambda self, c: {}})())
    monkeypatch.setattr(ato, "build_client_profile", lambda c: {})

    mock_db = MagicMock()
    mock_db.documents.insert.return_value = {"id": "doc-1"}
    _override(CLIENT, mock_db)
    try:
        resp = client.post(
            "/ato-response/upload",
            files={"file": ("letter.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={"engagement_id": "eng-1", "client_ref": "Acme Pty Ltd"},
        )
        assert resp.status_code == 200
        inserted = mock_db.documents.insert.call_args.args[0]
        assert inserted["engagement_id"] == "eng-1"
        assert inserted["client_ref"] == "Acme Pty Ltd"
        assert inserted["document_type"] == "ato_response"
        # Best-effort firm-client register upsert mirroring query/documents.
        mock_db.firm_clients.upsert.assert_called_once_with("client-1", "Acme Pty Ltd")
    finally:
        app.dependency_overrides.clear()


# --- engagement_id threaded into query-stream + document-generate payloads ---


@pytest.mark.asyncio
async def test_stream_query_insert_payload_includes_engagement_id():
    """The query-stream insert must carry engagement_id when supplied."""
    import taxflow.routers.query as q

    captured = {}
    mock_db = MagicMock()

    def _capture_insert(row):
        captured.update(row)
        return {"id": "query-1"}

    mock_db.queries.insert.side_effect = _capture_insert
    mock_db.queries.update.side_effect = lambda cid, qid, payload: None

    async def fake_astream(initial_state, stream_mode=None):
        yield ("custom", {"token": "hi"})
        yield ("values", {"answer": "hi", "citations": [], "confidence": 0.5,
                          "routed_tier": "haiku", "input_tokens": 1, "output_tokens": 1,
                          "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0})

    with patch.object(q, "embed", new=AsyncMock(return_value=[0.0] * 1536)), \
         patch.object(q, "increment_usage", new=AsyncMock()), \
         patch.object(q.research_graph, "astream", new=fake_astream), \
         patch.object(q.answer_cache, "store_answer", new=AsyncMock()), \
         patch.object(q.answer_cache, "get_cached_answer", new=AsyncMock(return_value=None)), \
         patch.object(q.answer_cache, "count_prior_asks", new=AsyncMock(return_value=0)):
        response = await q.stream_query(
            question="q",
            engagement_id="eng-1",
            client=CLIENT,
            _trial=CLIENT,
            db=mock_db,
        )
        _ = [c async for c in response.body_iterator]

    assert captured["engagement_id"] == "eng-1"
    assert captured["client_id"] == "client-1"


@pytest.mark.asyncio
async def test_generate_document_insert_payload_includes_engagement_id():
    import taxflow.routers.documents as d

    captured = {}
    mock_db = MagicMock()

    def _capture_insert(row):
        captured.update(row)
        return {"id": "doc-1"}

    mock_db.documents.insert.side_effect = _capture_insert

    async def fake_ainvoke(state):
        return {"result_md": state["content_md"]}

    body = d.GenerateDocumentRequest(
        document_type="advice_memo",
        title="Memo",
        content_md="body",
        engagement_id="eng-1",
    )
    with patch.object(d.document_graph, "ainvoke", new=fake_ainvoke), \
         patch.object(d.settings, "ENGAGEMENT_CONTEXT_ENABLED", False), \
         patch.object(d.settings, "LEARNING_LOOP_ENABLED", False):
        await d.generate_document(body=body, client=CLIENT, db=mock_db)

    assert captured["engagement_id"] == "eng-1"
    assert captured["client_id"] == "client-1"


# --- R2: cross-tenant engagement_id is rejected on every write path ----------


def _foreign_engagement_db():
    """A db whose engagements.get_for_client returns None — i.e. the supplied
    engagement_id is unknown or belongs to another tenant."""
    mock_db = MagicMock()
    mock_db.engagements.get_for_client.return_value = None
    return mock_db


def test_document_generate_rejects_foreign_engagement_id(client):
    mock_db = _foreign_engagement_db()
    _override(CLIENT, mock_db)
    try:
        resp = client.post(
            "/documents/generate",
            json={
                "document_type": "advice_memo",
                "title": "Memo",
                "content_md": "body",
                "engagement_id": "foreign-eng",
            },
        )
        assert resp.status_code == 404
        # The insert must never run for a spoofed engagement.
        mock_db.documents.insert.assert_not_called()
        mock_db.engagements.get_for_client.assert_called_once_with(
            "client-1", "foreign-eng"
        )
    finally:
        app.dependency_overrides.clear()


def test_ato_upload_rejects_foreign_engagement_id(client, monkeypatch):
    import taxflow.routers.ato_response as ato

    monkeypatch.setattr(ato, "_extract_text", lambda b: "letter text")

    mock_db = _foreign_engagement_db()
    _override(CLIENT, mock_db)
    try:
        resp = client.post(
            "/ato-response/upload",
            files={"file": ("letter.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={"engagement_id": "foreign-eng", "client_ref": "Acme"},
        )
        assert resp.status_code == 404
        mock_db.documents.insert.assert_not_called()
        mock_db.engagements.get_for_client.assert_called_once_with(
            "client-1", "foreign-eng"
        )
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stream_query_rejects_foreign_engagement_id():
    """The query stream must 404 (HTTPException) before inserting a row when the
    engagement_id is not the caller's."""
    import taxflow.routers.query as q
    from fastapi import HTTPException

    mock_db = _foreign_engagement_db()

    with pytest.raises(HTTPException) as exc:
        await q.stream_query(
            question="q",
            engagement_id="foreign-eng",
            client=CLIENT,
            _trial=CLIENT,
            db=mock_db,
        )
    assert exc.value.status_code == 404
    mock_db.queries.insert.assert_not_called()


# --- R1: cache-hit path persists engagement_id (not just the live path) ------


@pytest.mark.asyncio
async def test_stream_query_cache_hit_persists_engagement_id():
    """A cache hit persists a completed row via _persist_cached_query; it must
    carry engagement_id (previously the cached extra payload dropped it)."""
    import taxflow.routers.query as q

    captured = {}
    mock_db = MagicMock()
    # Not a foreign engagement — get_for_client returns a row so validation passes.
    mock_db.engagements.get_for_client.return_value = {"id": "eng-1"}

    def _capture_insert(row):
        captured.update(row)
        return {"id": "query-cached"}

    mock_db.queries.insert.side_effect = _capture_insert

    cached = {"answer": "cached answer", "citations": [], "confidence": 0.9}

    with patch.object(q, "increment_usage", new=AsyncMock()), \
         patch.object(
             q.answer_cache, "get_cached_answer", new=AsyncMock(return_value=cached)
         ), \
         patch.object(
             q.answer_cache, "count_prior_asks", new=AsyncMock(return_value=0)
         ):
        response = await q.stream_query(
            question="q",
            engagement_id="eng-1",
            client=CLIENT,
            _trial=CLIENT,
            db=mock_db,
        )
        _ = [c async for c in response.body_iterator]

    assert captured["engagement_id"] == "eng-1"
    assert captured["model_used"] == "cache"
