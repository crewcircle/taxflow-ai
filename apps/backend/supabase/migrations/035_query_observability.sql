-- Tier 1 (Task 1b/1c): per-query observability columns on `queries`.
--
-- Additive-only, all nullable: every statement is an ADD COLUMN with no
-- NOT NULL and no default that would rewrite existing rows. Legacy rows keep
-- NULL for every field (a cache-hit row stores cost_usd=0 explicitly from the
-- router, but leaves the validity/model_id columns NULL — callers treat NULL as
-- "not measured" via .get()). This keeps the migration a pure metadata change:
--   * citation_valid    — Task 1b: was the answer's [N] citation set valid?
--   * invalid_citations  — Task 1b: the fabricated/unmatched markers (jsonb blob).
--   * cost_usd           — Task 1b: dollar cost of the generation (run_cost).
--   * model_id           — Task 1c: the concrete resolved model id (resolve_model).
-- A purely additive-nullable migration needs no reversal.
ALTER TABLE queries ADD COLUMN citation_valid boolean;
ALTER TABLE queries ADD COLUMN invalid_citations jsonb;
ALTER TABLE queries ADD COLUMN cost_usd numeric;
ALTER TABLE queries ADD COLUMN model_id text;
