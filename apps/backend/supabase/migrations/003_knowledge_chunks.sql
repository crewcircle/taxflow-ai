CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE knowledge_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type text NOT NULL CHECK (source_type IN (
        'ato_ruling','ato_determination','ato_pbr','legislation','court_decision','ato_guide','ato_news'
    )),
    source_url text NOT NULL,
    source_title text NOT NULL,
    citation text NOT NULL,
    content text NOT NULL,
    embedding vector(1536),
    chunk_index integer NOT NULL DEFAULT 0,
    token_count integer,
    last_scraped_at timestamptz NOT NULL DEFAULT now(),
    effective_date date,
    is_current boolean NOT NULL DEFAULT true,
    UNIQUE (source_url, chunk_index)
);

CREATE INDEX ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX ON knowledge_chunks (source_type, is_current);
CREATE INDEX ON knowledge_chunks USING GIN (to_tsvector('english', content));
