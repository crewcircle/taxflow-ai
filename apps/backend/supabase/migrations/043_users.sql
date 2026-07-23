-- Real per-user identity within a firm, first step toward RBAC. Today one
-- `clients` row = one email = one Supabase Auth login = the entire tenant;
-- this table introduces individual logins (id = Supabase auth.users.id, the
-- JWT `sub`) that belong to a firm (clients.id) and carry a role.
--
-- `clients.email` keeps its existing meaning (the firm's primary contact/
-- billing email) - it is no longer the sole identity key for auth, `users.id`
-- is. Backfill below gives every existing clients row exactly one Owner user
-- so nothing breaks for firms that predate this table.
CREATE TABLE users (
    id           uuid PRIMARY KEY,
    client_id    uuid NOT NULL REFERENCES clients(id),
    email        text NOT NULL,
    role         text NOT NULL DEFAULT 'owner' CHECK (role IN ('owner', 'reviewer', 'staff')),
    display_name text,
    status       text NOT NULL DEFAULT 'active' CHECK (status IN ('invited', 'active', 'removed')),
    invited_by   uuid REFERENCES users(id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX ON users (client_id, lower(email));
CREATE INDEX ON users (client_id, status);

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON users USING (auth.role() = 'service_role');

-- Backfill: every existing clients row -> one Owner user, matched to its
-- already-provisioned Supabase Auth account by email. auth.users lives in
-- the same Postgres instance on real Supabase, so this is a plain join, not
-- an admin-API script. Guarded behind to_regclass so this migration also
-- applies cleanly against a bare Postgres with no `auth` schema at all (CI /
-- local integration test harness) - it just skips the backfill there, which
-- is fine since such a database has no real Supabase Auth users to match
-- anyway. A firm whose owner has never logged in on real Supabase (no
-- matching auth.users row yet) is likewise skipped here - it self-heals on
-- next login via the lazy-create fallback in middleware/auth.py.
DO $$
BEGIN
    IF to_regclass('auth.users') IS NOT NULL THEN
        INSERT INTO users (id, client_id, email, role, status)
        SELECT au.id, c.id, c.email, 'owner', 'active'
        FROM clients c
        JOIN auth.users au ON lower(au.email) = lower(c.email)
        ON CONFLICT (client_id, lower(email)) DO NOTHING;
    END IF;
END $$;
