-- Business audit follow-up (P0/P1/P2):
--
-- 1. knowledge_suggestions.assigned_to: explicit reviewer assignment for the
--    pending-suggestions queue, instead of "whoever notices the badge" (only
--    Owner-role users can ever be assigned, since approve/reject is
--    Owner-only - enforced in rbac.py, not here). assigned_by/assigned_at
--    record who set it and when, same pattern as decided_by/decided_at.
--
-- 2. Partial unique index on (client_id, source_query_id) WHERE status =
--    'pending': the application-level "exists_for_query" check before INSERT
--    (routers/query.py thumbs-up path, routers/firm_knowledge.py manual
--    promote path) is a check-then-act race - two near-simultaneous requests
--    (an automatic thumbs-up and a manual "Suggest for Firm Knowledge" click)
--    can both pass the check before either commits, producing two pending
--    suggestions for the same answer. The index makes the DB itself the
--    source of truth for "at most one pending suggestion per query", so the
--    two independent paths can never double-queue the same content even
--    under a race.
--
-- 3. users.regulatory_alerts_seen_at: the regulatory-updates "seen" cursor
--    lived in per-browser localStorage while every other notification kind
--    already has server-side read state (notifications.read_at). Regulatory
--    alerts themselves stay a global (not per-client) feed - only the
--    per-user "seen" cursor moves server-side here.

ALTER TABLE knowledge_suggestions ADD COLUMN assigned_to uuid REFERENCES users(id);
ALTER TABLE knowledge_suggestions ADD COLUMN assigned_by uuid REFERENCES users(id);
ALTER TABLE knowledge_suggestions ADD COLUMN assigned_at timestamptz;

CREATE UNIQUE INDEX idx_knowledge_suggestions_pending_dedup
    ON knowledge_suggestions (client_id, source_query_id)
    WHERE status = 'pending' AND source_query_id IS NOT NULL;

ALTER TABLE users ADD COLUMN regulatory_alerts_seen_at timestamptz;
