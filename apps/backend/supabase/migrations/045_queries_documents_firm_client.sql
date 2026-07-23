-- Real firm_client_id attribution on queries/documents, replacing the fragile
-- lower(client_ref) = lower(firm_clients.name) string-match join that
-- FirmClientsRepo.list_directory has relied on since 026 (queries/documents
-- never got a real FK to firm_clients - only the free-text client_ref column
-- from 012). Denormalized here (not resolved via a join to engagements on
-- every read) for the same reason engagement_id itself is denormalized on
-- these tables rather than always joined.
--
-- Nullable and additive - no backfill in this migration; historical rows are
-- backfilled separately by scripts/backfill_firm_client_ids.py so the DDL and
-- the (potentially slow, batched) data migration stay two distinct steps.
ALTER TABLE queries   ADD COLUMN firm_client_id uuid REFERENCES firm_clients(id);
ALTER TABLE documents ADD COLUMN firm_client_id uuid REFERENCES firm_clients(id);

CREATE INDEX ON queries   (client_id, firm_client_id);
CREATE INDEX ON documents (client_id, firm_client_id);
