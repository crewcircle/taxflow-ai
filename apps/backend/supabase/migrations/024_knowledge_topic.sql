-- Phase 3: categorise the knowledge base for the graph exploration UI.
-- Nullable, keyword-classified at ingest time (pipeline.py) - not retrieval-
-- critical, so a missing/wrong topic never affects answer quality, only
-- browsing/grouping in the explorer.
ALTER TABLE knowledge_chunks ADD COLUMN topic text;
CREATE INDEX ON knowledge_chunks (topic) WHERE topic IS NOT NULL;
