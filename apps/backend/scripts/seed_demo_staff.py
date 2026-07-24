"""One-time setup: add a Reviewer and a Staff login to each demo persona,
so the demo-login role switcher (routers/auth.py) has real accounts to pick
from - today every demo persona has only its original Owner login.

Uses the REAL Supabase invite flow (AuthPort.invite_user, the same call
POST /staff/invite makes) rather than seeding the `users` table directly, so
these are genuine Supabase Auth accounts a demo-login magic link can resolve
- not synthetic rows the auth layer has never heard of. The invite email
itself is never clicked (demo-login's existing generate_link + verify_otp
mechanism doesn't require a password / accepted invite either way).

Safe to re-run: skips any persona/role pair that already has a users row for
that synthetic email (checked via UsersRepo.get_by_client_and_email).

Run: doppler run --project taxflow --config prd -- \\
     uv run python scripts/seed_demo_staff.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from taxflow import providers  # noqa: E402
from taxflow.ports.auth import AuthError  # noqa: E402

# (owner_email, firm_slug) - firm_slug matches the existing demo email
# convention (scripts/seed_demo.py), so new emails read as siblings of the
# owner's: demo+<firm_slug>+<name>+<role>@crewcircle.com.au
PERSONA_STAFF = [
    {
        "owner_email": "demo+coogeebaydental+priya@crewcircle.com.au",
        "firm_slug": "coogeebaydental",
        "reviewer": ("sarah", "Sarah Mitchell"),
        "staff": ("james", "James Wong"),
    },
    {
        "owner_email": "demo+riversideproperty+david@crewcircle.com.au",
        "firm_slug": "riversideproperty",
        "reviewer": ("aisha", "Aisha Bello"),
        "staff": ("tom", "Tom Richards"),
    },
    {
        "owner_email": "demo+chenassociates+michael@crewcircle.com.au",
        "firm_slug": "chenassociates",
        "reviewer": ("grace", "Grace Liu"),
        "staff": ("daniel", "Daniel Foster"),
    },
    {
        "owner_email": "demo+enmorehospitality+elena@crewcircle.com.au",
        "firm_slug": "enmorehospitality",
        "reviewer": ("sofia", "Sofia Martins"),
        "staff": ("ryan", "Ryan Cooper"),
    },
    {
        "owner_email": "demo+nepeantradie+marcus@crewcircle.com.au",
        "firm_slug": "nepeantradie",
        "reviewer": ("chloe", "Chloe Anderson"),
        "staff": ("ben", "Ben Sharma"),
    },
]


def invite_demo_user(db, auth_port, client_id: str, owner_user_id: str, email: str, role: str, display_name: str) -> None:
    existing = db.users.get_by_client_and_email(client_id, email)
    if existing:
        print(f"  skip (exists): {email} [{role}]")
        return
    try:
        identity = auth_port.invite_user(email)
    except AuthError as e:
        print(f"  ERROR inviting {email}: {e}")
        return
    db.users.create(identity.sub, client_id, email, role, display_name, owner_user_id, "invited")
    print(f"  invited: {email} [{role}] -> {display_name}")


def run() -> None:
    db = providers.get_relational_data()
    auth_port = providers.get_auth_port()

    for persona in PERSONA_STAFF:
        client = db.clients.get_by_email(persona["owner_email"])
        if not client:
            print(f"SKIP {persona['owner_email']}: no clients row found")
            continue
        owner = db.users.get_by_client_and_email(client["id"], persona["owner_email"])
        if not owner:
            print(f"SKIP {persona['owner_email']}: no owner users row found")
            continue

        print(f"{client['business_name']} ({client['id']}):")
        rev_slug, rev_name = persona["reviewer"]
        staff_slug, staff_name = persona["staff"]
        rev_email = f"demo+{persona['firm_slug']}+{rev_slug}+reviewer@crewcircle.com.au"
        staff_email = f"demo+{persona['firm_slug']}+{staff_slug}+staff@crewcircle.com.au"

        invite_demo_user(db, auth_port, client["id"], owner["id"], rev_email, "reviewer", rev_name)
        invite_demo_user(db, auth_port, client["id"], owner["id"], staff_email, "staff", staff_name)


if __name__ == "__main__":
    run()
