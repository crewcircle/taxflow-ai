"""Shared helpers for the graph-RAG accuracy experiment scripts."""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(__file__)
QUESTIONS_PATH = os.path.join(HERE, "..", "..", "..", "tests", "accuracy", "questions.json")
MANIFEST_PATH = os.path.join(HERE, "manifest.json")
CORPUS_DIR = os.path.join(HERE, "corpus")
RESULTS_DIR = os.path.join(HERE, "results")

sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "src"))
# tests/ isn't normally on the path (it's not a package under src/) - add the
# backend root so `tests.accuracy.test_research_accuracy` imports cleanly.
sys.path.insert(0, os.path.join(HERE, "..", "..", ".."))


def load_questions() -> list[dict]:
    return json.loads(open(QUESTIONS_PATH).read())


def load_manifest() -> list[dict]:
    return json.loads(open(MANIFEST_PATH).read())


def score_answer(question: dict, result: dict) -> dict:
    """Reuse the REAL accuracy suite's scoring heuristic unmodified, so every
    pipeline (baseline, LightRAG, Cognee) is graded by the exact same rubric -
    the whole point of the comparison being fair."""
    from tests.accuracy.test_research_accuracy import score_answer as _score

    return _score(question, result)


def citations_from_context(context_text: str, manifest: list[dict]) -> list[dict]:
    """LightRAG/Cognee don't return citations shaped like ResearchAgent's
    `[{"citation": ...}]` - they return prose/context. Approximate the same
    shape by checking which corpus documents' citation labels appear in
    whatever context/answer text the pipeline returned, so score_answer()
    (which only looks at `c["citation"]` substrings) can grade it the same
    way it grades the baseline's real citations."""
    if not context_text:
        return []
    lower = context_text.lower()
    return [{"citation": m["citation"]} for m in manifest if m["citation"].lower() in lower]


def save_results(name: str, results: list[dict]) -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"{name}.json")
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved {len(results)} results -> {path}")


def load_results(name: str) -> list[dict]:
    path = os.path.join(RESULTS_DIR, f"{name}.json")
    return json.loads(open(path).read())
