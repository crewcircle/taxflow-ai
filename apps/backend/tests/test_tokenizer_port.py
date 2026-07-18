"""Tests for the TokenizerPort adapter and chunk_text migration (Task B9)."""

import re

import tiktoken

from taxflow import providers
from taxflow.adapters.tokenizer.tiktoken import TiktokenTokenizer
from taxflow.config import settings
from taxflow.ports.scrapers import TokenizerPort
from taxflow.services.knowledge import pipeline

_ref_encoder = tiktoken.get_encoding("cl100k_base")

SAMPLE_STRINGS = [
    "The quick brown fox jumps over the lazy dog.",
    "Division 7A applies to loans made by a private company to a shareholder.",
    "",
    "TR 2020/4 sets out the Commissioner's view on effective life of assets.",
]


def test_tokenizer_implements_port():
    assert isinstance(TiktokenTokenizer(), TokenizerPort)


def test_encode_matches_direct_tiktoken():
    tok = TiktokenTokenizer()
    for s in SAMPLE_STRINGS:
        assert tok.encode(s) == _ref_encoder.encode(s)


def test_count_matches_direct_tiktoken():
    tok = TiktokenTokenizer()
    for s in SAMPLE_STRINGS:
        assert tok.count(s) == len(_ref_encoder.encode(s))


def test_encoding_is_memoised():
    tok = TiktokenTokenizer()
    first = tok._get_encoding()
    second = tok._get_encoding()
    assert first is second


def test_provider_resolves_default_adapter():
    providers.reset_providers()
    tok = providers.get_tokenizer()
    assert isinstance(tok, TiktokenTokenizer)
    assert isinstance(tok, TokenizerPort)


def _expected_chunks(text: str, chunk_tokens: int, overlap_tokens: int) -> list[str]:
    """Reference implementation using tiktoken directly (pre-migration logic)."""
    sentences = re.compile(r"(?<=[.!?])\s+").split(text)
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for sentence in sentences:
        sentence_tokens = len(_ref_encoder.encode(sentence))
        if current and current_tokens + sentence_tokens > chunk_tokens:
            chunks.append(" ".join(current))
            kept: list[str] = []
            kept_tokens = 0
            for s in reversed(current):
                s_tokens = len(_ref_encoder.encode(s))
                if kept_tokens + s_tokens > overlap_tokens:
                    break
                kept.insert(0, s)
                kept_tokens += s_tokens
            current = kept
            current_tokens = kept_tokens
        current.append(sentence)
        current_tokens += sentence_tokens
    if current:
        chunks.append(" ".join(current))
    return [c.strip() for c in chunks if c.strip()]


def test_chunk_text_boundaries_match_direct_tiktoken():
    providers.reset_providers()
    # Build a document with many short sentences so chunking actually splits.
    text = " ".join(f"This is sentence number {i} about tax law." for i in range(200))

    for chunk_tokens, overlap_tokens in [(64, 8), (128, 16), (512, 64)]:
        expected = _expected_chunks(text, chunk_tokens, overlap_tokens)
        actual = pipeline.chunk_text(text, chunk_tokens=chunk_tokens, overlap_tokens=overlap_tokens)
        assert actual == expected
        assert len(actual) > 1  # sanity: the sample really does split


def test_chunk_text_default_settings_match():
    providers.reset_providers()
    text = " ".join(f"Sentence {i} discussing GST and BAS obligations." for i in range(300))
    expected = _expected_chunks(text, settings.CHUNK_SIZE_TOKENS, settings.CHUNK_OVERLAP_TOKENS)
    actual = pipeline.chunk_text(text)
    assert actual == expected
