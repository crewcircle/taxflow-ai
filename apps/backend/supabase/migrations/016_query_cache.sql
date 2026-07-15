-- Task B3: per-client DB-backed answer cache.
--
-- Prod runs 2 uvicorn workers (separate processes), so an in-process answer
-- cache can neither share hits nor be invalidated atomically across workers.
-- We back the cache in Postgres instead. Cache entries are keyed on the
-- normalised question + client_id + a knowledge_version token; an ingest bumps
-- the version (see knowledge_version below) so every worker instantly sees the
-- new version and all older rows become unreachable (atomic invalidation, no
-- cross-process signalling). A short TTL is a backstop.
--
-- Client isolation: entries are scoped by client_id and RLS-locked to the
-- service role, exactly like other tables (008_rls.sql). One client's cached
-- answer is never served to another (no cross-firm sharing, per the resolved
-- decision).

-- Single-row token bumped on every ingest to invalidate the whole cache.
CREATE TABLE knowledge_version (
    id boolean PRIMARY KEY DEFAULT true CHECK (id),  -- enforces a single row
    version bigint NOT NULL DEFAULT 1,
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO knowledge_version (id, version) VALUES (true, 1);

CREATE TABLE query_cache (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid NOT NULL REFERENCES clients(id),
    question_norm text NOT NULL,
    knowledge_version bigint NOT NULL,
    result jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (client_id, question_norm, knowledge_version)
);

CREATE INDEX idx_query_cache_lookup
    ON query_cache (client_id, question_norm, knowledge_version, created_at DESC);

-- RLS: mirror 008_rls.sql - service role has full access; no other role can read
-- another client's cached answers.
ALTER TABLE knowledge_version ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON knowledge_version USING (auth.role() = 'service_role');

ALTER TABLE query_cache ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON query_cache USING (auth.role() = 'service_role');
