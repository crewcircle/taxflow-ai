-- Answer-flow transparency: capture retrieval/generation/verification stage
-- detail on each query so the "why this answer?" UI can show it without
-- re-deriving it, and so it survives a page reload / history reopen.
ALTER TABLE queries ADD COLUMN trace jsonb;
