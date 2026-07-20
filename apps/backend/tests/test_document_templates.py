"""Phase 5: firm-level editable document templates.

Covers (all mocked — no real DB/LLM):
  - Repo SQL-shape + client_id scoping (Task 1).
  - The registry has exactly 18 editable keys (3 base + 15 ATO subtypes).
  - resolve_template: firm override vs system default; flag-off; ATO subtype
    fallthrough (subtype -> base -> default).
  - Drafting sites use the firm body when present (mocked LLM).
  - Settings routes: unknown key -> 400, empty body -> 400, PUT/GET round-trip,
    DELETE falls back to default, cross-firm isolation.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taxflow.adapters.db import repositories
from taxflow.adapters.db.repositories import Repositories
from taxflow.config import settings
from taxflow.services import document_templates as dt
from taxflow.services.ato_correspondence.classifier import LETTER_TYPES


# --- fake cursor harness (mirrors test_repositories.py) ----------------------


class _FakeCursor:
    def __init__(self, fetchone=None, fetchall=None):
        self.executed = []  # list of (sql, params)
        self._fetchone = fetchone
        self._fetchall = fetchall or []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._fetchone

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


# --- Task 1: repo SQL-shape + client_id scoping ------------------------------


def test_list_for_client_scoped_by_client():
    cur = _FakeCursor(fetchall=[])
    with _patch_conn(cur):
        Repositories().document_templates.list_for_client("client-1")
    sql, params = cur.executed[0]
    assert "FROM document_templates" in sql
    assert "WHERE client_id = %s" in sql
    assert params[0] == "client-1"


def test_get_for_key_scoped_by_client_and_key():
    cur = _FakeCursor(fetchone={"template_key": "advice_memo", "body": "b"})
    with _patch_conn(cur):
        Repositories().document_templates.get_for_key("client-1", "advice_memo")
    sql, params = cur.executed[0]
    assert "WHERE client_id = %s AND template_key = %s" in sql
    assert params == ("client-1", "advice_memo")


def test_upsert_uses_on_conflict_client_id_template_key():
    cur = _FakeCursor(fetchone={"id": "t1"})
    with _patch_conn(cur):
        Repositories().document_templates.upsert("client-1", "advice_memo", "body", "me@x")
    sql, params = cur.executed[0]
    assert "INSERT INTO document_templates" in sql
    assert "ON CONFLICT (client_id, template_key)" in sql
    assert "version = document_templates.version + 1" in sql
    assert params == ("client-1", "advice_memo", "body", "me@x")


def test_delete_scoped_by_client_and_key():
    cur = _FakeCursor()
    with _patch_conn(cur):
        Repositories().document_templates.delete("client-1", "advice_memo")
    sql, params = cur.executed[0]
    assert "DELETE FROM document_templates" in sql
    assert "WHERE client_id = %s AND template_key = %s" in sql
    assert params == ("client-1", "advice_memo")


# --- 18 editable keys (3 base + 15 ATO subtypes) -----------------------------


def test_exactly_18_editable_keys():
    keys = set(dt.SYSTEM_DEFAULTS)
    assert len(keys) == 18, f"expected 18 editable keys, got {len(keys)}"
    base = {"advice_memo", "client_letter", "ato_response"}
    assert base <= keys
    subtypes = {f"ato_response:{lt}" for lt in LETTER_TYPES}
    assert len(subtypes) == 15
    assert subtypes <= keys
    assert keys == base | subtypes
    # Labels mirror the keys.
    assert set(dt.TEMPLATE_LABELS) == keys


# --- resolve_template: firm override vs default; flag-off --------------------


def _fake_rd(get_for_key_return=None, list_return=None):
    rd = MagicMock()
    rd.document_templates.get_for_key.return_value = get_for_key_return
    rd.document_templates.list_for_client.return_value = list_return or []
    return rd


def test_resolve_returns_default_when_no_firm_row():
    with patch.object(settings, "DOCUMENT_TEMPLATES_ENABLED", True), patch.object(
        dt, "get_relational_data", return_value=_fake_rd(None)
    ):
        assert dt.resolve_template("cid", "advice_memo") == dt.SYSTEM_DEFAULTS["advice_memo"]


def test_resolve_returns_firm_body_when_row_present():
    row = {"body": "FIRM CUSTOM MEMO", "is_active": True}
    with patch.object(settings, "DOCUMENT_TEMPLATES_ENABLED", True), patch.object(
        dt, "get_relational_data", return_value=_fake_rd(row)
    ):
        assert dt.resolve_template("cid", "advice_memo") == "FIRM CUSTOM MEMO"


def test_resolve_ignores_empty_firm_body():
    # An empty/whitespace body always falls back to the system default. There is
    # no soft-delete state today (review S3), so is_active is not consulted.
    for row in ({"body": "   "}, {"body": ""}, {"body": None}):
        with patch.object(settings, "DOCUMENT_TEMPLATES_ENABLED", True), patch.object(
            dt, "get_relational_data", return_value=_fake_rd(row)
        ):
            assert dt.resolve_template("cid", "advice_memo") == dt.SYSTEM_DEFAULTS["advice_memo"]


def test_resolve_returns_default_when_flag_off():
    row = {"body": "FIRM CUSTOM MEMO", "is_active": True}
    with patch.object(settings, "DOCUMENT_TEMPLATES_ENABLED", False), patch.object(
        dt, "get_relational_data", return_value=_fake_rd(row)
    ) as _rd:
        assert dt.resolve_template("cid", "advice_memo") == dt.SYSTEM_DEFAULTS["advice_memo"]


def test_resolve_falls_back_to_default_on_db_error():
    rd = MagicMock()
    rd.document_templates.get_for_key.side_effect = RuntimeError("db down")
    with patch.object(settings, "DOCUMENT_TEMPLATES_ENABLED", True), patch.object(
        dt, "get_relational_data", return_value=rd
    ):
        assert dt.resolve_template("cid", "advice_memo") == dt.SYSTEM_DEFAULTS["advice_memo"]


def test_resolve_unknown_key_raises():
    with pytest.raises(KeyError):
        dt.resolve_template("cid", "not_a_template")


# --- ATO subtype fallthrough: subtype -> base -> default ---------------------


def test_ato_subtype_uses_subtype_row_when_present():
    key = "ato_response:penalty_notice"

    def get_for_key(client_id, template_key):
        return {"body": "SUBTYPE BODY", "is_active": True} if template_key == key else None

    rd = MagicMock()
    rd.document_templates.get_for_key.side_effect = get_for_key
    with patch.object(settings, "DOCUMENT_TEMPLATES_ENABLED", True), patch.object(
        dt, "get_relational_data", return_value=rd
    ):
        assert dt.resolve_template("cid", key) == "SUBTYPE BODY"


def test_ato_subtype_falls_through_to_base_when_subtype_unset():
    key = "ato_response:penalty_notice"

    def get_for_key(client_id, template_key):
        if template_key == "ato_response":
            return {"body": "BASE ATO BODY", "is_active": True}
        return None  # subtype unset

    rd = MagicMock()
    rd.document_templates.get_for_key.side_effect = get_for_key
    with patch.object(settings, "DOCUMENT_TEMPLATES_ENABLED", True), patch.object(
        dt, "get_relational_data", return_value=rd
    ):
        assert dt.resolve_template("cid", key) == "BASE ATO BODY"


def test_ato_subtype_falls_through_to_system_default_when_both_unset():
    key = "ato_response:penalty_notice"
    rd = MagicMock()
    rd.document_templates.get_for_key.return_value = None  # nothing set
    with patch.object(settings, "DOCUMENT_TEMPLATES_ENABLED", True), patch.object(
        dt, "get_relational_data", return_value=rd
    ):
        assert dt.resolve_template("cid", key) == dt.SYSTEM_DEFAULTS[key]
        # And the system default for a subtype == the base ato_response default.
        assert dt.SYSTEM_DEFAULTS[key] == dt.SYSTEM_DEFAULTS["ato_response"]


# --- list_templates_for_client ------------------------------------------------


def test_list_templates_marks_custom_rows():
    rows = [{"template_key": "advice_memo", "body": "custom"}]
    rd = _fake_rd(list_return=rows)
    with patch.object(settings, "DOCUMENT_TEMPLATES_ENABLED", True), patch.object(
        dt, "get_relational_data", return_value=rd
    ):
        out = dt.list_templates_for_client("cid")
    assert len(out) == 18
    memo = next(t for t in out if t["template_key"] == "advice_memo")
    assert memo["is_custom"] is True
    assert memo["body"] == "custom"
    assert memo["label"] == "Tax advice memo"
    other = next(t for t in out if t["template_key"] == "client_letter")
    assert other["is_custom"] is False
    assert other["body"] == dt.SYSTEM_DEFAULTS["client_letter"]


def test_list_templates_uses_single_query_no_n_plus_1():
    """S1: exactly ONE list_for_client query; resolution happens in-memory, so
    get_for_key is never called per key."""
    rd = _fake_rd(list_return=[{"template_key": "ato_response", "body": "base"}])
    with patch.object(settings, "DOCUMENT_TEMPLATES_ENABLED", True), patch.object(
        dt, "get_relational_data", return_value=rd
    ):
        out = dt.list_templates_for_client("cid")
    assert rd.document_templates.list_for_client.call_count == 1
    rd.document_templates.get_for_key.assert_not_called()
    # In-memory subtype->base fallthrough: an unset subtype resolves to the
    # firm's base ato_response row off the single-query map.
    subtype = next(t for t in out if t["template_key"] == "ato_response:penalty_notice")
    assert subtype["body"] == "base"
    assert subtype["is_custom"] is False


# --- Drafting sites use the firm body when present ---------------------------


@pytest.mark.asyncio
async def test_advice_memo_drafting_uses_firm_template():
    from taxflow.services.agents.draft import DraftAgent

    fake_llm = MagicMock()
    captured = {}

    async def fake_generate(messages, system, model, max_tokens, temperature):
        captured["system"] = system
        res = MagicMock()
        res.text = "SUMMARY\nLEGISLATIVE FRAMEWORK\nAPPLICATION TO FACTS\nCONCLUSION AND RECOMMENDED ACTION\nIMPORTANT LIMITATIONS"
        return res

    fake_llm.generate = AsyncMock(side_effect=fake_generate)
    agent = DraftAgent(llm=fake_llm)

    row = {"body": "FIRM MEMO PROMPT", "is_active": True}
    with patch.object(settings, "DOCUMENT_TEMPLATES_ENABLED", True), patch.object(
        dt, "get_relational_data", return_value=_fake_rd(row)
    ), patch(
        "taxflow.services.agents.draft.get_relational_data"
    ) as g:
        g.return_value.clients.get_voice_sample.return_value = ""
        await agent.run({"answer": "a", "citations": []}, "q", "cid")

    assert "FIRM MEMO PROMPT" in captured["system"]


@pytest.mark.asyncio
async def test_ato_drafting_uses_firm_subtype_template():
    from taxflow.services.ato_correspondence.drafter import ATOResponseDrafter

    fake_llm = MagicMock()
    captured = {}

    async def fake_generate(messages, system, model, max_tokens, temperature):
        # system may be a cacheable dict/list or a plain string.
        captured["system"] = system
        res = MagicMock()
        res.text = "letter"
        return res

    fake_llm.generate = AsyncMock(side_effect=fake_generate)
    drafter = ATOResponseDrafter(llm=fake_llm)

    key = "ato_response:penalty_notice"

    def get_for_key(client_id, template_key):
        return {"body": "FIRM ATO SUBTYPE PROMPT", "is_active": True} if template_key == key else None

    rd = MagicMock()
    rd.document_templates.get_for_key.side_effect = get_for_key
    with patch.object(settings, "DOCUMENT_TEMPLATES_ENABLED", True), patch.object(
        dt, "get_relational_data", return_value=rd
    ):
        await drafter.draft(
            classification={"letter_type": "penalty_notice", "ato_reference": "R1"},
            strategy={"response_strategy": "s"},
            original_letter="orig",
            client_id="cid",
        )

    assert "FIRM ATO SUBTYPE PROMPT" in str(captured["system"])


# --- flags-off parity (review B1) + code-owned AU-English (review B2) ---------


# The exact pre-Phase-5 advice-memo system prompt (role -> voice -> rest), used
# to assert byte-identical output with the flag off AND a voice sample present.
_VOICE_SAMPLE = "We write plainly and warmly."
_LEGACY_ADVICE_MEMO_SYSTEM = (
    "You are drafting a tax advice memo for an Australian accounting firm.\n"
    f'The firm describes its own voice like this - match this tone:\n"{_VOICE_SAMPLE}"\n\n'
    "Structure requirements (all sections mandatory):\n"
    "1. SUMMARY (2-3 sentences): Direct answer to the question asked.\n"
    "2. LEGISLATIVE FRAMEWORK: Key legislation and ATO positions that apply.\n"
    "   Cite every section using the reference numbers from the research.\n"
    "3. APPLICATION TO FACTS: How the law applies to this specific situation.\n"
    "4. CONCLUSION AND RECOMMENDED ACTION: What the client should do.\n"
    "5. IMPORTANT LIMITATIONS: Note that this is AI-assisted advice requiring\n"
    "   professional review before reliance.\n\n"
    "Use Australian English: organisation, recognise, licence (noun), practise (verb),\n"
    "lodgement, cheque, programme, centre, labour, behaviour.\n\n"
    "Do not include: generic disclaimers like 'this is general advice only',\n"
    "American spellings, passive voice without justification."
)


async def _capture_advice_memo_system(voice_sample: str) -> str:
    from taxflow.services.agents.draft import DraftAgent

    fake_llm = MagicMock()
    captured = {}

    async def fake_generate(messages, system, model, max_tokens, temperature):
        captured["system"] = system
        res = MagicMock()
        res.text = (
            "SUMMARY\nLEGISLATIVE FRAMEWORK\nAPPLICATION TO FACTS\n"
            "CONCLUSION AND RECOMMENDED ACTION\nIMPORTANT LIMITATIONS"
        )
        return res

    fake_llm.generate = AsyncMock(side_effect=fake_generate)
    agent = DraftAgent(llm=fake_llm)
    with patch("taxflow.services.agents.draft.get_relational_data") as g:
        g.return_value.clients.get_voice_sample.return_value = voice_sample
        await agent.run({"answer": "a", "citations": []}, "q", "cid")
    return captured["system"]


@pytest.mark.asyncio
async def test_flags_off_advice_memo_is_byte_identical_with_voice_sample():
    """B1: with the flag OFF and a voice sample present, the composed system
    prompt must be byte-identical to the pre-Phase-5 string (role line ->
    voice_instruction -> rest)."""
    with patch.object(settings, "DOCUMENT_TEMPLATES_ENABLED", False):
        system = await _capture_advice_memo_system(_VOICE_SAMPLE)
    assert system == _LEGACY_ADVICE_MEMO_SYSTEM


@pytest.mark.asyncio
async def test_au_english_always_present_even_if_firm_template_omits_it():
    """B2: a firm override that drops the AU-English instruction still gets it —
    the guardrail is code-owned and always enforced at the drafting site."""
    row = {"body": "Write however you like. No spelling rules."}
    with patch.object(settings, "DOCUMENT_TEMPLATES_ENABLED", True), patch.object(
        dt, "get_relational_data", return_value=_fake_rd(row)
    ):
        system = await _capture_advice_memo_system("")
    assert dt.AU_ENGLISH_MARKER in system
    assert "organisation" in system and "recognise" in system


def test_ensure_au_english_is_idempotent_on_default_body():
    """B2: ensure_au_english is a no-op when the guardrail is already present, so
    it never duplicates it in the code-owned default bodies."""
    default = (
        f"{dt.ADVICE_MEMO_ROLE}{dt.SYSTEM_DEFAULTS['advice_memo']}"
    )
    assert dt.ensure_au_english(default) == default
    # Appends exactly once when absent.
    stripped = "Draft nicely."
    once = dt.ensure_au_english(stripped)
    assert dt.AU_ENGLISH_MARKER in once
    assert dt.ensure_au_english(once) == once


# --- Settings routes ----------------------------------------------------------


@pytest.fixture
def app_client():
    from fastapi.testclient import TestClient

    from taxflow.main import app
    from taxflow.middleware.auth import get_current_client

    app.dependency_overrides[get_current_client] = lambda: {
        "id": "firm-1",
        "email": "firm1@example.com.au",
    }
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_put_rejects_unknown_template_key(app_client):
    r = app_client.put("/settings/templates/not_a_key", json={"body": "x"})
    assert r.status_code == 400


def test_put_rejects_empty_body(app_client):
    r = app_client.put("/settings/templates/advice_memo", json={"body": "   "})
    assert r.status_code == 400


def test_put_then_get_round_trips_firm_body(app_client):
    store: dict[tuple[str, str], dict] = {}

    def upsert(client_id, template_key, body, updated_by=None):
        row = {"template_key": template_key, "body": body, "is_active": True, "version": 1}
        store[(client_id, template_key)] = row
        return row

    def get_for_key(client_id, template_key):
        return store.get((client_id, template_key))

    def list_for_client(client_id):
        return [v for (c, _k), v in store.items() if c == client_id]

    rd = MagicMock()
    rd.document_templates.upsert.side_effect = upsert
    rd.document_templates.get_for_key.side_effect = get_for_key
    rd.document_templates.list_for_client.side_effect = list_for_client

    from taxflow.db import get_db
    from taxflow.main import app

    app.dependency_overrides[get_db] = lambda: rd
    with patch.object(settings, "DOCUMENT_TEMPLATES_ENABLED", True), patch.object(
        dt, "get_relational_data", return_value=rd
    ):
        try:
            r = app_client.put("/settings/templates/advice_memo", json={"body": "MY MEMO"})
            assert r.status_code == 200
            g = app_client.get("/settings/templates")
            assert g.status_code == 200
            memo = next(t for t in g.json() if t["template_key"] == "advice_memo")
            assert memo["body"] == "MY MEMO"
            assert memo["is_custom"] is True
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_delete_falls_back_to_default(app_client):
    rd = MagicMock()
    rd.document_templates.get_for_key.return_value = None
    rd.document_templates.list_for_client.return_value = []

    from taxflow.main import app
    from taxflow.db import get_db

    app.dependency_overrides[get_db] = lambda: rd
    with patch.object(settings, "DOCUMENT_TEMPLATES_ENABLED", True), patch.object(
        dt, "get_relational_data", return_value=rd
    ):
        try:
            d = app_client.delete("/settings/templates/advice_memo")
            assert d.status_code == 200
            rd.document_templates.delete.assert_called_once_with("firm-1", "advice_memo")
            g = app_client.get("/settings/templates")
            memo = next(t for t in g.json() if t["template_key"] == "advice_memo")
            assert memo["body"] == dt.SYSTEM_DEFAULTS["advice_memo"]
            assert memo["is_custom"] is False
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_cross_firm_isolation_on_get(app_client):
    """A firm only ever sees its own rows — repo is queried with its client_id."""
    seen_client_ids = []

    def list_for_client(client_id):
        seen_client_ids.append(client_id)
        return []

    rd = MagicMock()
    rd.document_templates.list_for_client.side_effect = list_for_client
    with patch.object(settings, "DOCUMENT_TEMPLATES_ENABLED", True), patch.object(
        dt, "get_relational_data", return_value=rd
    ):
        r = app_client.get("/settings/templates")
    assert r.status_code == 200
    assert seen_client_ids == ["firm-1"]
