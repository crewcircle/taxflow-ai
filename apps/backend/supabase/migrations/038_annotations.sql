-- Phase 1 (Core): in-app viewer + line/word-level annotations & comments.
--
-- One polymorphic ``annotations`` table serves BOTH generated documents and
-- query answers (and any future surface). ``target_type`` is the single
-- extension point: a new surface = extend the CHECK via a later additive
-- migration + one ownership-lookup branch in ``routers/annotations.py`` — no
-- table restructure.
--
-- ``target_id`` is intentionally NOT a foreign key (it is polymorphic across
-- ``queries``/``documents``); ownership is enforced in the router via
-- ``db.queries.get_for_client`` / ``db.documents.get_for_client``, mirroring
-- ``submit_feedback``. Because there is no FK to queries/documents, the
-- demo-reset path deletes annotations explicitly (see DemoResetRepo).
--
-- Additive-only: a single ``CREATE TABLE`` + ``CREATE INDEX`` + RLS
-- enable/policy; no ALTER/DROP of any existing table. RLS mirrors 037 exactly —
-- one ``service_role_full_access`` policy keyed on
-- ``auth.role() = 'service_role'`` (which provides NO tenant isolation on its
-- own; every repo statement carries ``WHERE client_id = %s`` as the real
-- tenant boundary).

CREATE TABLE annotations (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id     uuid NOT NULL REFERENCES clients(id),
    target_type   text NOT NULL CHECK (target_type IN ('query_answer','document')),
    target_id     uuid NOT NULL,           -- queries.id or documents.id (not FK: polymorphic)
    target_version text NOT NULL,          -- hash of the anchored source markdown (stale detection)
    block_index   int  NOT NULL,           -- index of the markdown block the span is in
    start_offset  int  NOT NULL,           -- char offset into source markdown (block-relative)
    end_offset    int  NOT NULL,
    quoted_text   text NOT NULL,           -- exact selected substring, for fuzzy re-anchor
    author_kind   text NOT NULL CHECK (author_kind IN ('reviewer','user')),
    author_name   text,                    -- free-text staff/user name (no per-user auth)
    body          text NOT NULL,
    parent_id     uuid REFERENCES annotations(id) ON DELETE CASCADE,  -- threads
    resolved_at   timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_annotations_target ON annotations (client_id, target_type, target_id);
CREATE INDEX idx_annotations_parent ON annotations (parent_id);

ALTER TABLE annotations ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON annotations USING (auth.role() = 'service_role');
