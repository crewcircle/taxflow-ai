"""Step 5: score baseline/lightrag/cognee results with the SAME score_answer()
heuristic the real accuracy suite uses, and print/save a comparison report.

Free to re-run - only reads results/*.json, makes no API calls.

Run: uv run python scripts/experiments/graphrag_accuracy/compare.py
"""
from __future__ import annotations

import os

from common import RESULTS_DIR, load_questions, load_results, score_answer

PIPELINES = ["baseline", "baseline_deepseek", "lightrag", "cognee"]
PASS_THRESHOLD = 4


def main() -> None:
    questions = load_questions()
    by_id = {q["id"]: q for q in questions}

    available = [p for p in PIPELINES if os.path.exists(os.path.join(RESULTS_DIR, f"{p}.json"))]
    if not available:
        print("No results found - run run_baseline.py / run_lightrag.py / run_cognee.py first.")
        return

    scored: dict[str, dict[str, dict]] = {}
    for pipeline in available:
        results = {r["id"]: r for r in load_results(pipeline)}
        scored[pipeline] = {
            qid: score_answer(by_id[qid], result) for qid, result in results.items() if qid in by_id
        }

    header = f"{'Question':<10}" + "".join(f"{p:>12}" for p in available)
    print(header)
    print("-" * len(header))
    for q in questions:
        row = f"{q['id']:<10}"
        for pipeline in available:
            s = scored[pipeline].get(q["id"])
            row += f"{(str(s['score']) + '/5') if s else 'n/a':>12}"
        print(row)

    print("-" * len(header))
    summary_row = f"{'PASS RATE':<10}"
    for pipeline in available:
        passed = sum(1 for s in scored[pipeline].values() if s["score"] >= PASS_THRESHOLD)
        total = len(scored[pipeline])
        summary_row += f"{f'{passed}/{total}':>12}"
    print(summary_row)

    # Markdown report
    lines = ["# Graph-RAG accuracy experiment results\n"]
    lines.append("| Question | " + " | ".join(available) + " |")
    lines.append("|---" * (len(available) + 1) + "|")
    for q in questions:
        cells = []
        for pipeline in available:
            s = scored[pipeline].get(q["id"])
            cells.append(f"{s['score']}/5" if s else "n/a")
        lines.append(f"| {q['id']} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## Pass rate (score >= 4/5, matching the real suite's bar)\n")
    for pipeline in available:
        passed = sum(1 for s in scored[pipeline].values() if s["score"] >= PASS_THRESHOLD)
        total = len(scored[pipeline])
        lines.append(f"- **{pipeline}**: {passed}/{total} ({round(100 * passed / total)}%)")

    report_path = os.path.join(RESULTS_DIR, "comparison.md")
    with open(report_path, "w") as f:
        f.write("\n".join(lines))
    print(f"\nWrote {report_path}")


if __name__ == "__main__":
    main()
