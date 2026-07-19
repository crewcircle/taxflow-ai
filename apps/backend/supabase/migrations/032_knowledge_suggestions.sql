-- Task C5: approval-gated learning loop (knowledge suggestions).
--
-- When a user thumbs-UP an answer, or a partner saves an advice_memo, a
-- SUGGESTION is created here rather than writing directly into the
-- authoritative firm_knowledge store. A principal then reviews pending
-- suggestions and either approves (embeds the content into firm_knowledge and
-- records the resulting firm_knowledge_id) or rejects them. This keeps the
-- approval gate mandatory: nothing on the feedback/promotion path writes
-- authoritative firm knowledge without an explicit approval (see the plan's
-- Decisions section).
--
-- RLS mirrors 006_firm_knowledge.sql / 030_engagement_context.sql: a single
-- service_role_full_access policy (auth.role() = 'service_role'); per-client
-- isolation is enforced by explicit WHERE client_id = %s predicates in the repo.

CREATE TABLE knowledge_suggestions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    source_query_id uuid REFERENCES queries(id),
    source_document_id uuid REFERENCES documents(id),
    title text NOT NULL,
    content text NOT NULL,
    reason text,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected')),
    decided_by text,
    decided_at timestamptz,
    firm_knowledge_id uuid REFERENCES firm_knowledge(id),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_knowledge_suggestions_client_status
    ON knowledge_suggestions (client_id, status, created_at DESC);

ALTER TABLE knowledge_suggestions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON knowledge_suggestions USING (auth.role() = 'service_role');
