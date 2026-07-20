-- Phase 2: first-class ``engagements`` entity.
--
-- Today units of work (``queries``, ``documents``, ATO responses) carry only an
-- optional free-text ``client_ref`` with NO foreign key to the firm's real
-- end-client register (``firm_clients``, migration 026). There is no attribution
-- guarantee and no engagement numbering. This migration adds a first-class
-- ``engagements`` table so every job is attributed to a real ``firm_clients`` row
-- and carries a per-firm-client sequential engagement number.
--
-- Naming (do not conflate): ``clients`` = TaxFlow's paying firms (the tenant);
-- ``client_id`` everywhere = tenant FK. ``firm_clients`` = a firm's OWN
-- end-clients. An ``engagement`` links a tenant (``client_id``) to one of its
-- end-clients (``firm_client_id``).
--
-- Additive-only: one ``CREATE TABLE`` + indexes + RLS enable/policy, plus
-- ``ALTER TABLE ... ADD COLUMN`` on existing tables (precedent: 012 added
-- ``client_ref``, 019 added ``session_id``). No DROP / ALTER COLUMN / ALTER TYPE
-- and no NOT-NULL-without-DEFAULT add on an existing table, so applying it cannot
-- rewrite or break existing rows or the Phase 1 annotations. RLS mirrors 038 /
-- 026 exactly — one ``service_role_full_access`` policy keyed on
-- ``auth.role() = 'service_role'`` (which gives NO tenant isolation on its own;
-- every repo statement carries ``WHERE client_id = %s`` as the real boundary).

CREATE TABLE engagements (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id         uuid NOT NULL REFERENCES clients(id),        -- tenant (TaxFlow's paying firm)
    firm_client_id    uuid NOT NULL REFERENCES firm_clients(id),   -- real end-client attribution
    engagement_number int  NOT NULL,                              -- sequential PER firm_client
    description       text NOT NULL,                              -- app-layer default applied when blank
    status            text NOT NULL DEFAULT 'active',
    created_by        text,
    created_at        timestamptz NOT NULL DEFAULT now()
);

-- Correctness backstop: engagement numbers are unique within a firm-client, so a
-- numbering collision (e.g. from a lost counter update) fails loudly instead of
-- silently duplicating a human-facing engagement number.
CREATE UNIQUE INDEX idx_engagements_firm_client_number ON engagements (firm_client_id, engagement_number);
CREATE INDEX idx_engagements_client_firm_client ON engagements (client_id, firm_client_id);

ALTER TABLE engagements ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON engagements USING (auth.role() = 'service_role');

-- Additive nullable link columns on the existing units of work. Nullable so no
-- existing row breaks and Phase 1 annotations (which target queries/documents
-- directly) are unaffected; ``client_ref`` stays for back-compat and backfill.
ALTER TABLE queries   ADD COLUMN engagement_id uuid REFERENCES engagements(id);
ALTER TABLE documents ADD COLUMN engagement_id uuid REFERENCES engagements(id);

-- Per-firm-client engagement-number counter. Incremented via
-- ``UPDATE ... RETURNING`` in the SAME transaction as the engagement insert
-- (a single row-lock per firm-client, tenant-scoped), so concurrent creates for
-- one client serialise cleanly and different clients never block each other.
-- DEFAULT 0 so the add is additive (no NOT-NULL-without-default rewrite).
ALTER TABLE firm_clients ADD COLUMN next_engagement_seq int NOT NULL DEFAULT 0;
