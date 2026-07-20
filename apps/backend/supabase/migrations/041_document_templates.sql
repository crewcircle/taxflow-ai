-- Phase 5 (Decision #2523): firm-level editable document templates.
--
-- Firm-level (clients = TaxFlow's paying firm) editable document templates.
-- ``template_key`` is this table's OWN column, deliberately NOT tied to the
-- ``documents_document_type_check`` CHECK constraint (migration 005/027) — so we
-- never touch that CHECK (nor the ``LetterType`` assert in agents/models.py) and
-- future ATO letter-subtype keys (``ato_response:{letter_type}``) need no
-- migration. Resolution at draft time is: firm row body else the code-owned
-- system default (services/document_templates.py).
--
-- Additive-only: a single ``CREATE TABLE`` + ``CREATE UNIQUE INDEX`` + RLS
-- enable/policy for the new table, plus ONE additive nullable
-- ``ALTER TABLE documents ADD COLUMN`` (no DROP/ALTER COLUMN/ALTER TYPE, no
-- backfill). RLS mirrors 026/037 exactly — one ``service_role_full_access``
-- policy keyed on ``auth.role() = 'service_role'``.

CREATE TABLE document_templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid NOT NULL REFERENCES clients(id),
    template_key text NOT NULL,
    name text,
    body text NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    version integer NOT NULL DEFAULT 1,
    updated_by text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX ON document_templates (client_id, template_key);

ALTER TABLE document_templates ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON document_templates USING (auth.role() = 'service_role');

-- Additive structural column: the classified ATO letter type. Today the letter
-- type lives ONLY in the free-text ``documents.title`` (routers/ato_response.py);
-- a real column is required to resolve the per-subtype template
-- (``ato_response:{letter_type}``) and to trace provenance. Nullable, no
-- backfill, so applying this cannot rewrite or break existing rows.
ALTER TABLE documents ADD COLUMN ato_letter_type text;
