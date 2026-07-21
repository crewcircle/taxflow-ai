-- Backfill firm_clients from existing documents.client_ref / queries.client_ref
-- history. register_firm_client() (routers/_shared.py) only upserts a row
-- going forward, on a best-effort basis that used to fail silently - so any
-- client whose only history predates this firm_clients table (026), or whose
-- registering job hit a transient error, has real work sitting under its name
-- in documents/queries but no row here. That's exactly what made the "Who is
-- this for?" picker (GET /firm-clients?search=) unable to find real,
-- existing clients: it only ever searched this table.
--
-- ON CONFLICT DO NOTHING is safe against the existing
-- UNIQUE (client_id, lower(name)) index - re-running this is a no-op.
INSERT INTO firm_clients (client_id, name)
SELECT DISTINCT client_id, client_ref
FROM documents
WHERE client_ref IS NOT NULL AND btrim(client_ref) <> ''
ON CONFLICT DO NOTHING;

INSERT INTO firm_clients (client_id, name)
SELECT DISTINCT client_id, client_ref
FROM queries
WHERE client_ref IS NOT NULL AND btrim(client_ref) <> ''
ON CONFLICT DO NOTHING;
