CREATE TABLE documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid NOT NULL REFERENCES clients(id),
    query_id uuid REFERENCES queries(id),
    document_type text NOT NULL CHECK (document_type IN (
        'advice_memo','ato_response','remission_request','objection_letter',
        'private_ruling_application','engagement_letter','payg_variation','fbt_declaration'
    )),
    title text NOT NULL,
    content_md text NOT NULL,
    content_docx bytea,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','sent','archived')),
    approved_by text,
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
