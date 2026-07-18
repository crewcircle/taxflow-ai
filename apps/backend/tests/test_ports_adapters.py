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
