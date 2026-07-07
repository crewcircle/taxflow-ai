CREATE TABLE firm_knowledge (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    file_name text NOT NULL,
    file_type text NOT NULL CHECK (file_type IN ('pdf','docx','txt')),
    content text NOT NULL,
    embedding vector(1536),
    usage_count integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ON firm_knowledge USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);
