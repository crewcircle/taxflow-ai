-- A firm's own client register, built organically: rows are upserted the
-- first time a name is used as queries.client_ref / documents.client_ref
-- (both stay plain text - no FK here, so existing history with inconsistent
-- casing isn't broken). This table is the autocomplete source of truth that
-- turns the free-text "Client (optional)" field into a real register after
-- its first use, without requiring firms to pre-seed a client list upfront.
--
-- Naming note: `clients` is TaxFlow's own paying firms. `firm_clients` is
-- that firm's own clients - two different things with unfortunately similar
-- names, kept distinct on purpose rather than overloading `clients` further.
CREATE TABLE firm_clients (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid NOT NULL REFERENCES clients(id),
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- A plain UNIQUE table constraint can't take a function expression like
-- lower(name) - a unique index is the correct (and, for ON CONFLICT
-- purposes, equivalent) way to enforce this.
CREATE UNIQUE INDEX ON firm_clients (client_id, lower(name));
CREATE INDEX ON firm_clients (client_id, name);

ALTER TABLE firm_clients ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON firm_clients USING (auth.role() = 'service_role');
