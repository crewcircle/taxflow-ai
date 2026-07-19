-- Task C4: engagement context store (embed-on-save + scoped retrieval).
--
-- When a partner saves an approved client-facing document (advice_memo,
-- objection_letter, ato_response, engagement_letter), the content is embedded
-- and stored here so future research queries scoped to the SAME client_ref can
-- retrieve prior engagement memos as advisory context. This is deliberately a
-- SEPARATE table from firm_knowledge: auto-embedded engagement memos stay out
-- of the approval-gated firm_knowledge store until a suggestion is explicitly
-- approved (see the plan's Decisions section).
--
-- RLS mirrors 006_firm_knowledge.sql / 008_rls.sql: a single
-- service_role_full_access policy (auth.role() = 'service_role'); per-client
-- isolation is enforced by explicit WHERE client_id = %s predicates in the repo,
-- and retrieval is further scoped by client_ref.

CREATE TABLE engagement_context (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    client_ref text,
    document_id uuid REFERENCES documents(id),
    document_type text,
    title text,
    content text NOT NULL,
    embedding vector(1536),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ON engagement_context USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);
CREATE INDEX idx_engagement_context_client_ref ON engagement_context (client_id, client_ref);

ALTER TABLE engagement_context ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON engagement_context USING (auth.role() = 'service_role');
