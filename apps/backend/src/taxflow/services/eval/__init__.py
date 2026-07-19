"""Offline eval harness (Workstream B).

Pure, dependency-light building blocks that separate the three failure modes of
the research pipeline — retrieval, generation and citation validity — and let us
A/B a model swap on quality-per-dollar.

Everything in this package except :mod:`taxflow.services.eval.judge` is pure and
runs offline (no LLM / DB / network). The judge routes through
``providers.get_llm()`` so it obeys the same ports-and-adapters and
model-routing invariants as every production call-site.
"""
