-- Phase 3 (Generic CRUD + content editing): additive columns for in-app
-- content editing + soft-delete of research queries.
--
-- Additive-only, all nullable: every statement is an ADD COLUMN with no
-- NOT NULL and no default that would rewrite existing rows. Legacy rows keep
-- NULL for every field (callers treat NULL as "never edited" / "not deleted"
-- via .get()/IS NULL). This keeps the migration a pure metadata change:
--   * documents.edited_at — set to now() when a document's content_md/title is
--     edited in-app (PATCH /documents/{id}); NULL means never edited.
--   * queries.edited_at   — set to now() when a query answer (final_answer) is
--     edited in-app (PATCH /query/{id}); NULL means never edited.
--   * queries.deleted_at  — soft-delete tombstone: set to now() when a query is
--     archived. Every read path filters `deleted_at IS NULL` so archived rows
--     are hidden from history, session context, prior-ask counts and analytics
--     but retained for the record. NULL means live.
-- A purely additive-nullable migration needs no reversal.
ALTER TABLE documents ADD COLUMN edited_at timestamptz;
ALTER TABLE queries ADD COLUMN edited_at timestamptz;
ALTER TABLE queries ADD COLUMN deleted_at timestamptz;
