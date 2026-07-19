-- Workstream C (Task C1): partial index supporting parent-expansion lookups.
--
-- Kept in a SEPARATE migration from 033 so 033 stays ADD COLUMN-only (its
-- additive-only test forbids anything but ADD COLUMN). This partial index
-- groups a source's child chunks by their parent unit for the parent-expansion
-- read path; only rows that actually carry a parent_key are indexed (legacy
-- flat rows have parent_key IS NULL and are excluded).
CREATE INDEX ON knowledge_chunks (source_url, parent_key) WHERE parent_key IS NOT NULL;
