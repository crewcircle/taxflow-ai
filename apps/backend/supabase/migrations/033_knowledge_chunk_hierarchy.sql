-- Workstream C (Task C1): structure-aware / hierarchical chunking columns.
--
-- Additive-only, all nullable: every statement is an ADD COLUMN with no
-- NOT NULL and no default that would rewrite existing rows. Legacy/flat rows
-- keep NULL for the hierarchy fields (chunk_level is set to 'flat' by the
-- ingest pipeline going forward; existing rows read as NULL, which callers
-- treat as flat via .get()). This keeps the migration a pure metadata change
-- and lets both flags (HIERARCHICAL_CHUNKING_ENABLED / PARENT_EXPANSION_ENABLED)
-- default off = today's exact behaviour. The optional partial index on
-- (source_url, parent_key) ships separately in 034_knowledge_parent_index.sql
-- so this migration stays ADD COLUMN-only.
ALTER TABLE knowledge_chunks ADD COLUMN heading_path text;
ALTER TABLE knowledge_chunks ADD COLUMN section_ref text;
ALTER TABLE knowledge_chunks ADD COLUMN chunk_level text;
ALTER TABLE knowledge_chunks ADD COLUMN parent_key text;
ALTER TABLE knowledge_chunks ADD COLUMN parent_content text;
