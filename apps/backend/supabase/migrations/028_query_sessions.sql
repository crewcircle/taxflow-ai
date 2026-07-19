-- Names the conversation thread that queries.session_id already groups
-- (added in 019_queries_session_id.sql for follow-up context, but never
-- surfaced to users). One row per thread, created on first rename rather
-- than on every question - a session with no label just isn't renamed yet.
CREATE TABLE query_sessions (
    session_id uuid PRIMARY KEY,
    client_id uuid NOT NULL REFERENCES clients(id),
    label text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE query_sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON query_sessions USING (auth.role() = 'service_role');
