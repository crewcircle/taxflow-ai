-- Phase 2: state payroll tax + stamp duty/land tax public rulings.
-- One new source_type covers every state (the specific tax type and
-- jurisdiction are carried by citation/title text and this new jurisdiction
-- column, not by source_type itself - adding 8 more source_type values for
-- 8 states would bloat the CHECK constraint for no retrieval benefit).
ALTER TABLE knowledge_chunks DROP CONSTRAINT knowledge_chunks_source_type_check;
ALTER TABLE knowledge_chunks ADD CONSTRAINT knowledge_chunks_source_type_check
    CHECK (source_type IN (
        'ato_ruling','ato_determination','ato_pbr','legislation','court_decision',
        'ato_guide','ato_news','state_ruling'
    ));

-- NULL for existing (federal) rows; state scrapers set this to 'NSW'/'VIC'/etc.
ALTER TABLE knowledge_chunks ADD COLUMN jurisdiction text;
CREATE INDEX ON knowledge_chunks (jurisdiction) WHERE jurisdiction IS NOT NULL;
