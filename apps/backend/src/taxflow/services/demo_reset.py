"""Nightly cleanup for the shared public demo account so query/document
history doesn't accumulate indefinitely or leak between visitors."""
import psycopg2

from taxflow.config import settings


def reset_demo_data() -> None:
    conn = psycopg2.connect(settings.DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT id FROM clients WHERE is_demo = true")
    demo_ids = [row[0] for row in cur.fetchall()]

    if demo_ids:
        cur.execute("DELETE FROM documents WHERE client_id = ANY(%s)", (demo_ids,))
        cur.execute("DELETE FROM queries WHERE client_id = ANY(%s)", (demo_ids,))
        conn.commit()
        print(f"demo reset: cleared queries/documents for {len(demo_ids)} demo client(s)")

    cur.close()
    conn.close()
