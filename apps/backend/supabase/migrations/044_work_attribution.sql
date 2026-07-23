-- Per-row author attribution, needed for RBAC's "can delete own work, not
-- someone else's" rule and general "who actually did this" visibility.
-- Nullable and additive - historical rows predate individual logins (043)
-- and stay NULL; only new inserts populate this going forward.
ALTER TABLE queries     ADD COLUMN created_by_user_id uuid REFERENCES users(id);
ALTER TABLE documents   ADD COLUMN created_by_user_id uuid REFERENCES users(id);
ALTER TABLE engagements ADD COLUMN created_by_user_id uuid REFERENCES users(id);

-- engagements.created_by (free text, 039) stays as-is for historical display -
-- this is the real FK-based version for anything created after 043 gave firms
-- real per-user logins.
