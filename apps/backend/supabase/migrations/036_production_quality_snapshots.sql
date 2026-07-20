-- Task 3a-1: production quality drift snapshots.
--
-- A daily leader-guarded drift job aggregates the trailing production window
-- (Tier-2 QueriesRepo.stats) against a longer baseline window, diffs the two,
-- and persists ONE row here per run. metrics/diff are opaque jsonb blobs
-- (the rolled-up aggregate + the per-metric deltas/regressions from
-- services.eval.drift), so the schema never has to change when the metric set
-- evolves. has_regressions is the one denormalised flag the admin dashboard /
-- ops alert read without parsing the jsonb.
--
-- NEW TABLE only (no ALTER/DROP of any existing table). RLS mirrors mig 030 /
-- 008_rls.sql: a single service_role_full_access policy; this table is
-- operator-scoped (no client_id), read behind the admin token.

CREATE TABLE production_quality_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    window_start timestamptz,
    window_end timestamptz,
    baseline_start timestamptz,
    baseline_end timestamptz,
    metrics jsonb NOT NULL,
    diff jsonb,
    has_regressions boolean NOT NULL DEFAULT false,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX idx_production_quality_snapshots_created ON production_quality_snapshots (created_at DESC);

ALTER TABLE production_quality_snapshots ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON production_quality_snapshots USING (auth.role() = 'service_role');
