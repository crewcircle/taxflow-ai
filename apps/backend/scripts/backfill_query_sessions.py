"""Phase 3: one-time query_sessions backfill (guarded data step, NOT
migration 046 - 046 is additive-schema-only).

query_sessions rows were, until Phase 3's eager-creation change, only ever
created lazily on first rename - so most conversation threads have no row at
all. This script gives every distinct historical ``queries.session_id`` a
real ``query_sessions`` row (attribution taken from that session's most
recent query), and is the precondition for safely running the separate
follow-up ``ALTER TABLE queries VALIDATE CONSTRAINT queries_session_id_fkey``
(NOT run by this script - see 046's own comment for why that step stays
manual and separate).

Idempotency: only ever reads/writes sessions with no existing query_sessions
row (``distinct_sessions_missing_row`` / ``get_or_create``'s own ON CONFLICT
DO NOTHING), so a second run finds nothing left to do.

Run: doppler run --project taxflow --config prd -- \\
     uv run python scripts/backfill_query_sessions.py [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from taxflow.providers import get_relational_data  # noqa: E402


def run_backfill(*, dry_run: bool) -> None:
    db = get_relational_data()
    sessions = db.query_sessions.distinct_sessions_missing_row()
    print(f"query_sessions backfill: {len(sessions)} session(s) missing a row, dry_run={dry_run}")

    if dry_run:
        for s in sessions:
            print(
                f"  DRY-RUN session={s['session_id']} client={s['client_id']} "
                f"-> engagement={s.get('engagement_id')} firm_client={s.get('firm_client_id')}"
            )
        return

    for s in sessions:
        try:
            db.query_sessions.get_or_create(
                s["client_id"], s["session_id"], s.get("engagement_id"), s.get("firm_client_id")
            )
            status = f"OK session={s['session_id']} client={s['client_id']}"
        except Exception as e:  # noqa: BLE001 - one bad session must not kill the run
            status = f"ERROR session={s.get('session_id')}: {e}"
        print(f"  {status}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-time query_sessions backfill (Phase 3).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the sessions that would be backfilled without writing anything.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    run_backfill(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
