ALTER TABLE knowledge_chunks ADD COLUMN superseded_by text;
CREATE INDEX ON knowledge_chunks (is_current) WHERE is_current = false;
