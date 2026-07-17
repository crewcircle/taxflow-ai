-- Task D3: lightweight session memory keyed on an explicit session_id.
--
-- The dashboard UI mints a session_id (uuid) per conversation and reuses it
-- across turns; "new chat" starts a fresh one. When a query carries a
-- session_id, the agent loads the last N prior queries for that
-- (client_id, session_id) and prepends a compact "conversation so far" block.
-- Session context is auto-injected ONLY within the same session_id, never
-- across sessions or clients. Single-shot queries (no session_id) are
-- unaffected — the column is nullable.
ALTER TABLE queries ADD COLUMN session_id uuid;

-- Supports the session-memory read: filter by (client_id, session_id) and order
-- by created_at to fetch the most recent prior turns cheaply.
CREATE INDEX ON queries (client_id, session_id, created_at);
