-- Async verification results, demo account flag, and contact form submissions.

ALTER TABLE queries ADD COLUMN verification_result jsonb;

ALTER TABLE clients ADD COLUMN is_demo boolean NOT NULL DEFAULT false;

CREATE TABLE contact_messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    email text NOT NULL,
    firm_name text,
    message text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE contact_messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON contact_messages USING (auth.role() = 'service_role');
