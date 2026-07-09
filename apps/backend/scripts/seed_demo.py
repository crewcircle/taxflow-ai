"""
One-time setup for the public demo account. Safe to re-run - upserts rather
than duplicating.

Run: doppler run --project taxflow --config prd -- \
     uv run python scripts/seed_demo.py
"""
import os

from supabase import create_client

DEMO_EMAIL = "demo@taxflow.crewcircle.com.au"


def main() -> None:
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

    existing = sb.table("clients").select("id").eq("email", DEMO_EMAIL).execute()
    if existing.data:
        client_id = existing.data[0]["id"]
        sb.table("clients").update({"is_demo": True}).eq("id", client_id).execute()
        print(f"Demo client already exists: {client_id} (is_demo confirmed)")
    else:
        result = (
            sb.table("clients")
            .insert(
                {
                    "business_name": "TaxFlow Demo Firm",
                    "business_type": "accounting",
                    "email": DEMO_EMAIL,
                    "suburb": "Sydney",
                    "state": "NSW",
                    "is_demo": True,
                    "subscription_status": "active",  # never trial-gated
                    "tier": "professional",
                }
            )
            .execute()
        )
        client_id = result.data[0]["id"]
        sb.table("trials").insert(
            {
                "client_id": client_id,
                "trial_status": "active",
                "queries_cap": 100000,
                "docs_cap": 100000,
            }
        ).execute()
        print(f"Created demo client: {client_id}")

    print(f"Demo login is ready: POST /auth/demo-login logs visitors into {DEMO_EMAIL}")


if __name__ == "__main__":
    main()
