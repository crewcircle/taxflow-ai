-- Task C5: user feedback capture on answers.
--
-- Thumbs up/down (+ optional free-text note) on a query result, RLS-scoped per
-- client like other tables (008_rls.sql). The feedback endpoint enforces that
-- the referenced query_id belongs to the requesting client, so one client can
-- never attach feedback to (or probe the existence of) another client's query.

CREATE TABLE query_feedback (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    query_id uuid NOT NULL REFERENCES queries(id),
    client_id uuid NOT NULL REFERENCES clients(id),
    rating text NOT NULL CHECK (rating IN ('up', 'down')),
    note text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_query_feedback_query ON query_feedback (query_id);
CREATE INDEX idx_query_feedback_client ON query_feedback (client_id, created_at DESC);

ALTER TABLE query_feedback ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON query_feedback USING (auth.role() = 'service_role');
