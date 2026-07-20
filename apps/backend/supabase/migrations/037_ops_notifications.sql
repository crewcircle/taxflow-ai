-- Task 3a-0 (Decision #2485): ops-scoped notification schema.
--
-- Operator-facing notifications (e.g. drift alerts) are NOT per-client, so they
-- live in a NEW ``ops_notifications`` table with NO ``client_id`` column rather
-- than relaxing the existing per-client ``notifications.client_id NOT NULL``
-- constraint (030_re_research_jobs_notifications.sql). The existing
-- ``notifications`` table stays per-client with its RLS intact; this table is
-- operator-scoped and read behind the admin token.
--
-- Additive-only: a single ``CREATE TABLE`` + ``CREATE INDEX`` + RLS enable/policy;
-- no ALTER/DROP of any existing table. RLS mirrors 030 exactly — one
-- ``service_role_full_access`` policy keyed on ``auth.role() = 'service_role'``.

CREATE TABLE ops_notifications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind text NOT NULL,
    title text,
    body text,
    metadata jsonb,
    severity text,
    read_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_ops_notifications_created ON ops_notifications (created_at DESC);

ALTER TABLE ops_notifications ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON ops_notifications USING (auth.role() = 'service_role');
