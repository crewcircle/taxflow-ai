"""One-time fix for demo data seeded before seed_demo.py created real
engagement/conversation attribution (see seed_demo.py's per-question
``engagement_desc`` and ``_attribute_matter``).

Those earlier rows still have the right ``firm_client`` name (via an older
backfill) but every one of them shares a single generic "General
(backfilled)" engagement per firm_client - even matters that are clearly
distinct (e.g. Coogee Bay Dental's "Smile Bay Dental" firm_client covers both
the CBCT scanner write-off AND the unrelated Division 7A loan). None of them
have a session_id, so there is also no named conversation thread.

This script re-derives the correct per-matter engagement (using the same
``_attribute_matter`` helper seed_demo.py now seeds new data with) for each
already-seeded demo query/document, by matching on question text /
client_ref, and repoints engagement_id/firm_client_id/session_id in place.

Idempotent: a query with a non-null session_id is treated as already fixed
and skipped.

Run: doppler run --project taxflow --config prd -- \\
     uv run python scripts/fix_demo_engagements.py [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from taxflow import providers  # noqa: E402
from seed_demo import PERSONAS, _attribute_matter  # noqa: E402


def fix_persona(db, persona: dict, *, dry_run: bool) -> None:
    client = db.clients.get_by_email(persona["email"])
    if not client:
        print(f"  {persona['business_name']}: no client found - skipping")
        return
    client_id = client["id"]
    print(f"{persona['business_name']} ({persona['email']}):")

    queries = db.queries.list_recent(client_id, limit=50)
    by_question = {q["question"]: q for q in queries}

    first_item = persona["questions"][0]
    ato_attribution = None
    first_attribution = None

    for item in persona["questions"]:
        query = by_question.get(item["question"])
        if not query:
            print(f"    no matching query row for: {item['question'][:60]}...")
            continue
        if query.get("session_id"):
            print(f"    already fixed: {item['engagement_desc']}")
            if item["client_ref"] == persona["ato_client_ref"]:
                ato_attribution = {
                    "engagement_id": query["engagement_id"],
                    "firm_client_id": query["firm_client_id"],
                }
            if item is first_item:
                first_attribution = {
                    "engagement_id": query["engagement_id"],
                    "firm_client_id": query["firm_client_id"],
                }
            continue

        if dry_run:
            print(f"    [dry-run] would attribute '{item['engagement_desc']}' to query {query['id']}")
            continue

        attribution = _attribute_matter(db, client_id, item["client_ref"], item["engagement_desc"])
        session_id = str(uuid.uuid4())
        db.query_sessions.get_or_create(
            client_id, session_id, attribution["engagement_id"], attribution["firm_client_id"]
        )
        db.query_sessions.upsert_label(client_id, session_id, item["engagement_desc"])
        db.queries.update(
            client_id,
            query["id"],
            {
                "engagement_id": attribution["engagement_id"],
                "firm_client_id": attribution["firm_client_id"],
                "session_id": session_id,
            },
        )
        print(f"    fixed: {item['engagement_desc']} -> session {session_id}")
        if item["client_ref"] == persona["ato_client_ref"]:
            ato_attribution = attribution
        if item is first_item:
            first_attribution = attribution

    if dry_run:
        return

    documents = db.documents.list_for_client(client_id)
    for doc in documents:
        if doc["document_type"] == "advice_memo" and first_attribution:
            db.documents.update(
                client_id,
                doc["id"],
                {
                    "engagement_id": first_attribution["engagement_id"],
                    "firm_client_id": first_attribution["firm_client_id"],
                },
            )
            print(f"    fixed document: {doc['title']}")
        elif doc["document_type"] == "ato_response" and ato_attribution:
            db.documents.update(
                client_id,
                doc["id"],
                {
                    "engagement_id": ato_attribution["engagement_id"],
                    "firm_client_id": ato_attribution["firm_client_id"],
                },
            )
            print(f"    fixed document: {doc['title']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = providers.get_relational_data()
    for persona in PERSONAS:
        fix_persona(db, persona, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
