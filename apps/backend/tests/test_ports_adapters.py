"""Tests for the LiteLLM LLM adapter + LLMPort wiring (Task A1).

``litellm.acompletion`` is monkeypatched so no real API calls are made. We
assert usage mapping for both Anthropic- and OpenAI-style usage objects, the
streaming contract (text chunks then a terminal ``done=True`` usage chunk),
structured-output validation + ``StructuredParseError`` fallback, and defensive
bare-Claude-ID model prefixing.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from taxflow.adapters.llm import litellm_adapter
from taxflow.adapters.llm.litellm_adapter import LiteLLMAdapter
from taxflow.ports.llm import LLMPort, StreamChunk, StructuredParseError


# --- fakes -------------------------------------------------------------------
class _Obj:
    """Simple attribute bag standing in for LiteLLM's response objects."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _anthropic_usage():
    return _Obj(
        input_tokens=100,
        output_tokens=42,
        cache_read_input_tokens=30,
        cache_creation_input_tokens=10,
    )


def _openai_usage():
    return _Obj(
        prompt_tokens=100,
        completion_tokens=42,
        prompt_tokens_details=_Obj(cached_tokens=30),
    )


def _completion_response(content: str, usage) -> _Obj:
    message = _Obj(content=content)
    choice = _Obj(message=message)
    return _Obj(choices=[choice], usage=usage)


def _fake_acompletion(response, capture: dict):
    async def _inner(**kwargs):
        capture.update(kwargs)
        return response

    return _inner


def _fake_stream_acompletion(text_pieces, usage, capture: dict):
    async def _inner(**kwargs):
        capture.update(kwargs)

        async def _agen():
            for piece in text_pieces:
                delta = _Obj(content=piece)
                yield _Obj(choices=[_Obj(delta=delta)], usage=None)
            # terminal usage-only chunk: empty choices, usage populated
            yield _Obj(choices=[], usage=usage)

        return _agen()

    return _inner


# --- generate: usage mapping -------------------------------------------------
@pytest.mark.asyncio
async def test_generate_maps_text_and_anthropic_usage(monkeypatch):
    capture: dict = {}
    resp = _completion_response("hello world", _anthropic_usage())
    monkeypatch.setattr(litellm_adapter.litellm, "acompletion", _fake_acompletion(resp, capture))

    adapter = LiteLLMAdapter()
    result = await adapter.generate(
        messages=[{"role": "user", "content": "hi"}],
        system="be helpful",
        model="anthropic/claude-sonnet-4-6",
        max_tokens=256,
    )

    assert result.text == "hello world"
    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 42
    assert result.usage.cache_read_input_tokens == 30
    assert result.usage.cache_creation_input_tokens == 10
    # system prepended as a message
    assert capture["messages"][0] == {"role": "system", "content": "be helpful"}
    assert capture["messages"][1] == {"role": "user", "content": "hi"}


@pytest.mark.asyncio
async def test_generate_forwards_api_key(monkeypatch):
    """The composition root injects the configured ANTHROPIC_API_KEY; the adapter
    must forward it to litellm.acompletion (BaseSettings env_file does not export
    into os.environ, so implicit env lookup would break key-only-in-.env runs)."""
    capture: dict = {}
    resp = _completion_response("hello", _anthropic_usage())
    monkeypatch.setattr(litellm_adapter.litellm, "acompletion", _fake_acompletion(resp, capture))

    adapter = LiteLLMAdapter(api_key="sk-test-anthropic")
    await adapter.generate(
        messages=[{"role": "user", "content": "hi"}],
        model="anthropic/claude-haiku-4-5",
        max_tokens=128,
    )

    assert capture["api_key"] == "sk-test-anthropic"


@pytest.mark.asyncio
async def test_generate_maps_openai_style_usage(monkeypatch):
    capture: dict = {}
    resp = _completion_response("hi", _openai_usage())
    monkeypatch.setattr(litellm_adapter.litellm, "acompletion", _fake_acompletion(resp, capture))

    adapter = LiteLLMAdapter()
    result = await adapter.generate(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-4o",
        max_tokens=256,
    )

    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 42
    assert result.usage.cache_read_input_tokens == 30  # from prompt_tokens_details
    assert result.usage.cache_creation_input_tokens == 0
    # no system -> no system message prepended
    assert capture["messages"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_generate_normalizes_bare_claude_id(monkeypatch):
    capture: dict = {}
    resp = _completion_response("x", _anthropic_usage())
    monkeypatch.setattr(litellm_adapter.litellm, "acompletion", _fake_acompletion(resp, capture))

    adapter = LiteLLMAdapter()
    await adapter.generate(
        messages=[{"role": "user", "content": "hi"}],
        model="claude-haiku-4-5",
        max_tokens=128,
    )
    assert capture["model"] == "anthropic/claude-haiku-4-5"


# --- stream ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stream_yields_text_then_terminal_usage(monkeypatch):
    capture: dict = {}
    monkeypatch.setattr(
        litellm_adapter.litellm,
        "acompletion",
        _fake_stream_acompletion(["Hel", "lo"], _anthropic_usage(), capture),
    )

    adapter = LiteLLMAdapter()
    chunks: list[StreamChunk] = []
    # NOTE: no await on the stream() call itself
    async for chunk in adapter.stream(
        messages=[{"role": "user", "content": "hi"}],
        model="claude-haiku-4-5",
        max_tokens=128,
    ):
        chunks.append(chunk)

    text_chunks = [c for c in chunks if c.text]
    assert "".join(c.text for c in text_chunks) == "Hello"
    terminal = chunks[-1]
    assert terminal.done is True
    assert terminal.usage is not None
    assert terminal.usage.input_tokens == 100
    assert terminal.usage.output_tokens == 42
    # streaming knobs forwarded, bare claude id normalized
    assert capture["stream"] is True
    assert capture["stream_options"] == {"include_usage": True}
    assert capture["model"] == "anthropic/claude-haiku-4-5"


# --- generate_structured -----------------------------------------------------
class _Sample(BaseModel):
    name: str
    score: int


@pytest.mark.asyncio
async def test_generate_structured_returns_validated_model(monkeypatch):
    capture: dict = {}
    resp = _completion_response('{"name": "abc", "score": 5}', _anthropic_usage())
    monkeypatch.setattr(litellm_adapter.litellm, "acompletion", _fake_acompletion(resp, capture))

    adapter = LiteLLMAdapter()
    out = await adapter.generate_structured(
        messages=[{"role": "user", "content": "give json"}],
        model="claude-haiku-4-5",
        output_model=_Sample,
        max_tokens=128,
    )
    assert isinstance(out, _Sample)
    assert out.name == "abc"
    assert out.score == 5
    assert capture["response_format"] is _Sample
    assert capture["model"] == "anthropic/claude-haiku-4-5"


@pytest.mark.asyncio
async def test_generate_structured_raises_on_malformed_json(monkeypatch):
    resp = _completion_response("not json at all", _anthropic_usage())
    monkeypatch.setattr(litellm_adapter.litellm, "acompletion", _fake_acompletion(resp, {}))

    adapter = LiteLLMAdapter()
    with pytest.raises(StructuredParseError):
        await adapter.generate_structured(
            messages=[{"role": "user", "content": "give json"}],
            model="anthropic/claude-haiku-4-5",
            output_model=_Sample,
            max_tokens=128,
        )


@pytest.mark.asyncio
async def test_generate_structured_raises_on_validation_error(monkeypatch):
    # valid JSON, wrong shape (score is not an int-coercible value)
    resp = _completion_response('{"name": "abc", "score": "not-an-int"}', _anthropic_usage())
    monkeypatch.setattr(litellm_adapter.litellm, "acompletion", _fake_acompletion(resp, {}))

    adapter = LiteLLMAdapter()
    with pytest.raises(StructuredParseError):
        await adapter.generate_structured(
            messages=[{"role": "user", "content": "give json"}],
            model="anthropic/claude-haiku-4-5",
            output_model=_Sample,
            max_tokens=128,
        )


# --- protocol / normalizer ---------------------------------------------------
def test_adapter_satisfies_llmport():
    assert isinstance(LiteLLMAdapter(), LLMPort)


def test_normalize_model_leaves_prefixed_and_non_claude():
    assert litellm_adapter._normalize_model("anthropic/claude-haiku-4-5") == "anthropic/claude-haiku-4-5"
    assert litellm_adapter._normalize_model("gpt-4o") == "gpt-4o"
    assert litellm_adapter._normalize_model("claude-haiku-4-5") == "anthropic/claude-haiku-4-5"


# --- resolve_model tier resolution (Workstream A) ----------------------------
def test_resolve_model_maps_named_agent_tiers(monkeypatch):
    from taxflow import providers
    from taxflow.config import settings

    monkeypatch.setattr(
        settings,
        "MODEL_TIER_MAP",
        {
            "haiku": "anthropic/claude-haiku-4-5",
            "sonnet": "anthropic/claude-sonnet-4-6",
            "draft": "anthropic/claude-haiku-4-5",
            "verify": "anthropic/claude-haiku-4-5",
            "rerank": "anthropic/claude-haiku-4-5",
            "classify": "anthropic/claude-haiku-4-5",
            "verify_strong": "anthropic/claude-sonnet-4-6",
        },
    )
    assert providers.resolve_model("draft") == "anthropic/claude-haiku-4-5"
    assert providers.resolve_model("verify") == "anthropic/claude-haiku-4-5"
    assert providers.resolve_model("rerank") == "anthropic/claude-haiku-4-5"
    assert providers.resolve_model("classify") == "anthropic/claude-haiku-4-5"
    assert providers.resolve_model("verify_strong") == "anthropic/claude-sonnet-4-6"


def test_resolve_model_alias_fallback_when_agent_tier_absent(monkeypatch):
    """An agent tier missing from the map falls back via _TIER_ALIAS to the base
    tier's mapping (haiku/sonnet)."""
    from taxflow import providers
    from taxflow.config import settings

    monkeypatch.setattr(
        settings,
        "MODEL_TIER_MAP",
        {"haiku": "anthropic/claude-haiku-4-5", "sonnet": "anthropic/claude-sonnet-4-6"},
    )
    # draft/verify/rerank/classify -> haiku; verify_strong -> sonnet
    assert providers.resolve_model("draft") == "anthropic/claude-haiku-4-5"
    assert providers.resolve_model("verify") == "anthropic/claude-haiku-4-5"
    assert providers.resolve_model("rerank") == "anthropic/claude-haiku-4-5"
    assert providers.resolve_model("classify") == "anthropic/claude-haiku-4-5"
    assert providers.resolve_model("verify_strong") == "anthropic/claude-sonnet-4-6"


def test_resolve_model_returns_opencode_value_verbatim(monkeypatch):
    """An OpenCode-style value set in the map is returned verbatim (no prefixing)."""
    from taxflow import providers
    from taxflow.config import settings

    monkeypatch.setattr(
        settings,
        "MODEL_TIER_MAP",
        {"haiku": "openai/glm-5", "draft": "openai/deepseek-v4-flash"},
    )
    assert providers.resolve_model("draft") == "openai/deepseek-v4-flash"
    # alias fallback also returns the verbatim OpenCode value
    assert providers.resolve_model("rerank") == "openai/glm-5"


def test_resolve_model_unknown_tier_returns_itself(monkeypatch):
    from taxflow import providers
    from taxflow.config import settings

    monkeypatch.setattr(settings, "MODEL_TIER_MAP", {})
    # not a base tier, not an alias, no legacy entry -> returned verbatim
    assert providers.resolve_model("openai/some-model") == "openai/some-model"
    assert providers.resolve_model("totally-unknown") == "totally-unknown"


def test_resolve_model_legacy_fallback_prefixes_bare_claude(monkeypatch):
    """With the base tier absent from the map, the legacy ANTHROPIC_*_MODEL field
    is used and a bare Claude ID is anthropic/-prefixed. Agent tiers reach it via
    the alias (draft -> haiku -> legacy ANTHROPIC_HAIKU_MODEL)."""
    from taxflow import providers
    from taxflow.config import settings

    monkeypatch.setattr(settings, "MODEL_TIER_MAP", {})
    monkeypatch.setattr(settings, "ANTHROPIC_HAIKU_MODEL", "claude-haiku-4-5")
    monkeypatch.setattr(settings, "ANTHROPIC_SONNET_MODEL", "claude-sonnet-4-6")
    assert providers.resolve_model("haiku") == "anthropic/claude-haiku-4-5"
    assert providers.resolve_model("sonnet") == "anthropic/claude-sonnet-4-6"
    assert providers.resolve_model("draft") == "anthropic/claude-haiku-4-5"
    assert providers.resolve_model("verify_strong") == "anthropic/claude-sonnet-4-6"


# --- adapter threads api_base ------------------------------------------------
@pytest.mark.asyncio
async def test_generate_forwards_api_base(monkeypatch):
    capture: dict = {}
    resp = _completion_response("hi", _anthropic_usage())
    monkeypatch.setattr(litellm_adapter.litellm, "acompletion", _fake_acompletion(resp, capture))

    adapter = LiteLLMAdapter(api_key="k", api_base="https://x/v1")
    await adapter.generate(
        messages=[{"role": "user", "content": "hi"}],
        model="anthropic/claude-haiku-4-5",
        max_tokens=128,
    )
    assert capture["api_base"] == "https://x/v1"


@pytest.mark.asyncio
async def test_stream_forwards_api_base(monkeypatch):
    capture: dict = {}
    monkeypatch.setattr(
        litellm_adapter.litellm,
        "acompletion",
        _fake_stream_acompletion(["a", "b"], _anthropic_usage(), capture),
    )
    adapter = LiteLLMAdapter(api_key="k", api_base="https://x/v1")
    async for _chunk in adapter.stream(
        messages=[{"role": "user", "content": "hi"}],
        model="anthropic/claude-haiku-4-5",
        max_tokens=128,
    ):
        pass
    assert capture["api_base"] == "https://x/v1"


@pytest.mark.asyncio
async def test_generate_structured_forwards_api_base(monkeypatch):
    capture: dict = {}
    resp = _completion_response('{"name": "abc", "score": 5}', _anthropic_usage())
    monkeypatch.setattr(litellm_adapter.litellm, "acompletion", _fake_acompletion(resp, capture))

    adapter = LiteLLMAdapter(api_key="k", api_base="https://x/v1")
    await adapter.generate_structured(
        messages=[{"role": "user", "content": "give json"}],
        model="anthropic/claude-haiku-4-5",
        output_model=_Sample,
        max_tokens=128,
    )
    assert capture["api_base"] == "https://x/v1"


@pytest.mark.asyncio
async def test_generate_api_base_none_when_not_passed(monkeypatch):
    capture: dict = {}
    resp = _completion_response("hi", _anthropic_usage())
    monkeypatch.setattr(litellm_adapter.litellm, "acompletion", _fake_acompletion(resp, capture))

    adapter = LiteLLMAdapter()  # no api_base
    await adapter.generate(
        messages=[{"role": "user", "content": "hi"}],
        model="anthropic/claude-haiku-4-5",
        max_tokens=128,
    )
    assert capture["api_base"] is None


# --- get_llm() key/base resolution -------------------------------------------
@pytest.fixture
def _reset_llm_cache():
    """Ensure the memoised LLM adapter is cleared after monkeypatching settings,
    so a stale adapter can't leak into later tests."""
    from taxflow import providers

    yield
    providers.reset_providers()


def _configure_llm(monkeypatch, *, base="", llm_key="", opencode_key="", anthropic_key="sk-anthropic"):
    from taxflow import providers
    from taxflow.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "LLM_API_BASE", base)
    monkeypatch.setattr(settings, "LLM_API_KEY", llm_key)
    monkeypatch.setattr(settings, "OPENCODE_API_KEY", opencode_key)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", anthropic_key)
    providers.reset_providers()
    return providers


def test_get_llm_base_and_llm_key_set(monkeypatch, _reset_llm_cache):
    providers = _configure_llm(
        monkeypatch, base="https://x/v1", llm_key="sk-generic", opencode_key="sk-oc"
    )
    adapter = providers.get_llm()
    assert adapter._api_base == "https://x/v1"
    assert adapter._api_key == "sk-generic"


def test_get_llm_all_empty_uses_anthropic(monkeypatch, _reset_llm_cache):
    providers = _configure_llm(monkeypatch, anthropic_key="sk-anthropic")
    adapter = providers.get_llm()
    assert adapter._api_base is None
    assert adapter._api_key == "sk-anthropic"


def test_get_llm_opencode_key_ignored_when_base_empty(monkeypatch, _reset_llm_cache):
    """The opt-in guard: OPENCODE_API_KEY present but LLM_API_BASE empty => the
    Anthropic key is used, never the OpenCode key."""
    providers = _configure_llm(
        monkeypatch, base="", opencode_key="sk-oc", anthropic_key="sk-anthropic"
    )
    adapter = providers.get_llm()
    assert adapter._api_base is None
    assert adapter._api_key == "sk-anthropic"


def test_get_llm_base_plus_opencode_uses_opencode(monkeypatch, _reset_llm_cache):
    providers = _configure_llm(
        monkeypatch, base="https://x/v1", opencode_key="sk-oc", anthropic_key="sk-anthropic"
    )
    adapter = providers.get_llm()
    assert adapter._api_base == "https://x/v1"
    assert adapter._api_key == "sk-oc"


def test_get_llm_llm_key_wins_over_opencode(monkeypatch, _reset_llm_cache):
    providers = _configure_llm(
        monkeypatch,
        base="https://x/v1",
        llm_key="sk-generic",
        opencode_key="sk-oc",
        anthropic_key="sk-anthropic",
    )
    adapter = providers.get_llm()
    assert adapter._api_key == "sk-generic"
