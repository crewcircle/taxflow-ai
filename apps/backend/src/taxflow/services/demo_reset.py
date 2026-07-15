"""Nightly cleanup for the shared public demo account so query/document
history doesn't accumulate indefinitely or leak between visitors."""
from taxflow.db import get_pg_conn


def reset_demo_data() -> None:
    with get_pg_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM clients WHERE is_demo = true")
        demo_ids = [row[0] for row in cur.fetchall()]

        if demo_ids:
            cur.execute("DELETE FROM documents WHERE client_id = ANY(%s)", (demo_ids,))
            cur.execute("DELETE FROM queries WHERE client_id = ANY(%s)", (demo_ids,))
            conn.commit()
            print(f"demo reset: cleared queries/documents for {len(demo_ids)} demo client(s)")

        cur.close()
