"""Phase 2: one-time firm_client_id backfill (guarded data step, NOT migration
045 - 045 is additive-schema-only, this fills the new nullable column).

What it does, across ALL tenants:
1. ``link_via_engagement``: every queries/documents row that already has an
   ``engagement_id`` (from the earlier 042 engagement backfill, or from
   normal runtime use before this script ever runs) gets its
   ``firm_client_id`` copied straight from that engagement. Pure SQL join,
   idempotent (only touches ``firm_client_id IS NULL`` rows).
2. For the rarer remainder - a row with BOTH ``firm_client_id`` and
   ``engagement_id`` still NULL (predates even the 042 engagement backfill,
   or was created in the gap between deploys) - resolve that tenant's
   "Unattributed" bucket (the exact same sentinel
   ``routers/_shared.py::resolve_or_default_engagement`` uses at runtime, so
   this converges on whatever bucket 042/live traffic already created rather
   than minting a second one) and link every such row to it.

Idempotency: both passes only ever touch ``firm_client_id IS NULL`` rows, so
a second run finds nothing left to do.

Run: doppler run --project taxflow --config prd -- \\
     uv run python scripts/backfill_firm_client_ids.py [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from taxflow.providers import get_relational_data  # noqa: E402
from taxflow.routers._shared import (  # noqa: E402
    LIVE_UNATTRIBUTED_DESCRIPTION,
    UNATTRIBUTED_FIRM_CLIENT_NAME,
)


def resolve_orphan_client(db, client_id: str, *, dry_run: bool) -> str:
    """Resolve (and link) one tenant's fully-orphaned rows. Returns a status line."""
    if dry_run:
        return f"DRY-RUN client={client_id} -> would resolve Unattributed bucket and link"

    firm_client = db.firm_clients.create(client_id, UNATTRIBUTED_FIRM_CLIENT_NAME)
    engagement = db.engagements.get_by_firm_client_and_description(
        client_id, firm_client["id"], LIVE_UNATTRIBUTED_DESCRIPTION
    )
    if not engagement:
        engagement = db.engagements.create(
            client_id, firm_client["id"], LIVE_UNATTRIBUTED_DESCRIPTION
        )
    linked = db.firm_client_backfill.link_orphans_to_engagement(
        client_id, engagement["id"], firm_client["id"]
    )
    return f"OK client={client_id} -> Unattributed bucket, linked {linked} row(s)"


def run_backfill(*, dry_run: bool) -> None:
    db = get_relational_data()

    if dry_run:
        orphan_clients = db.firm_client_backfill.distinct_fully_orphaned_clients()
        print(
            "firm_client_id backfill (dry-run): would link every row with a real "
            "engagement_id via join, then resolve the Unattributed bucket for "
            f"{len(orphan_clients)} tenant(s) with fully-orphaned rows: {orphan_clients}"
        )
        return

    linked_via_engagement = db.firm_client_backfill.link_via_engagement()
    print(f"Linked {linked_via_engagement} row(s) via existing engagement_id join")

    orphan_clients = db.firm_client_backfill.distinct_fully_orphaned_clients()
    print(f"{len(orphan_clients)} tenant(s) still have fully-orphaned rows")
    for client_id in orphan_clients:
        try:
            status = resolve_orphan_client(db, client_id, dry_run=False)
        except Exception as e:  # noqa: BLE001 - one bad tenant must not kill the run
            status = f"ERROR client={client_id}: {e}"
        print(f"  {status}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-time firm_client_id backfill (Phase 2).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would happen without writing anything.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    run_backfill(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
