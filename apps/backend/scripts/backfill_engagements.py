"""Phase 2: one-time engagement backfill (guarded data step, NOT migration 039).

Migration 039 is additive-schema-only (its ``test_migration_039_additive.py``
guard forbids DML), so linking legacy rows to engagements lives here as a
separate, idempotent, client-scoped data step.

What it does, per tenant (``client_id``):
- Find every distinct ``(client_id, normalised client_ref)`` bucket across
  ``queries`` + ``documents`` that still has ``engagement_id IS NULL`` rows.
  ``client_ref`` is normalised via ``NULLIF(TRIM(client_ref), '')`` so blank /
  whitespace-only refs collapse into a single NULL bucket.
- For a NAMED bucket: get-or-create the ``firm_clients`` row for that name and
  create ONE "General" engagement for it.
- For the NULL bucket (all legacy ATO uploads land here — they persist no
  ``client_ref``): get-or-create a single synthetic ``firm_clients`` row named
  ``"General / Unattributed"`` per tenant so ``engagements.firm_client_id``
  (NOT NULL) is always satisfiable, then create one "General" engagement for it.
- Link every unlinked row in the bucket to that engagement.

Numbering: engagements are created through the SAME
``EngagementsRepo.create`` runtime path, so each firm-client's
``next_engagement_seq`` is advanced via ``UPDATE ... RETURNING`` exactly as it is
at runtime — post-backfill runtime numbering can never collide with a backfilled
number.

Idempotency: ``distinct_unlinked_buckets`` only returns buckets with unlinked
rows and ``link_bucket`` only touches ``engagement_id IS NULL`` rows, so a second
run finds no buckets and changes nothing. ``firm_clients.create`` is get-or-create
so a re-run would not duplicate the client register either.

Run: doppler run --project taxflow --config prd -- \\
     uv run python scripts/backfill_engagements.py [--client-id <uuid>] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from taxflow.providers import get_relational_data  # noqa: E402

UNATTRIBUTED_NAME = "General / Unattributed"
BACKFILL_DESCRIPTION = "General (backfilled)"


def _bucket_client_name(client_ref: str | None) -> str:
    """Firm-client name for a bucket: the real ref, or the synthetic
    unattributed bucket for NULL/blank refs (incl. all legacy ATO uploads)."""
    return client_ref if client_ref else UNATTRIBUTED_NAME


def backfill_bucket(db, bucket: dict, *, dry_run: bool) -> str:
    """Process one ``(client_id, client_ref)`` bucket. Returns a status line."""
    client_id = bucket["client_id"]
    client_ref = bucket.get("client_ref")  # already normalised (NULL for blank)
    name = _bucket_client_name(client_ref)

    if dry_run:
        return f"DRY-RUN client={client_id} ref={client_ref!r} -> firm_client={name!r}"

    # 1) get-or-create the firm_clients row (real id), tenant-scoped.
    fc = db.firm_clients.create(client_id, name)
    firm_client_id = fc["id"]

    # 2) create ONE "General" engagement via the runtime path (advances
    #    next_engagement_seq through UPDATE ... RETURNING).
    engagement = db.engagements.create(
        client_id, firm_client_id, BACKFILL_DESCRIPTION, "backfill"
    )

    # 3) link every unlinked row in the bucket (idempotent: engagement_id IS NULL).
    linked = db.engagement_backfill.link_bucket(
        client_id, client_ref, engagement["id"]
    )
    return (
        f"OK client={client_id} ref={client_ref!r} "
        f"-> engagement #{engagement['engagement_number']} ({name!r}), linked {linked} row(s)"
    )


def run_backfill(*, client_id: str | None, dry_run: bool) -> None:
    db = get_relational_data()
    buckets = db.engagement_backfill.distinct_unlinked_buckets(client_id)
    print(
        f"Engagement backfill: {len(buckets)} unlinked bucket(s), "
        f"client_id={client_id or 'ALL'}, dry_run={dry_run}"
    )
    for bucket in buckets:
        try:
            status = backfill_bucket(db, bucket, dry_run=dry_run)
        except Exception as e:  # noqa: BLE001 - one bad bucket must not kill the run
            status = f"ERROR client={bucket.get('client_id')} ref={bucket.get('client_ref')!r}: {e}"
        print(f"  {status}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-time engagement backfill (Phase 2).")
    parser.add_argument(
        "--client-id", type=str, default=None, help="Only backfill this tenant."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the buckets that would be backfilled without writing anything.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    run_backfill(client_id=args.client_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
