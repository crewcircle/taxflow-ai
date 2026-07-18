ALTER TABLE firm_knowledge DROP CONSTRAINT firm_knowledge_file_type_check;
ALTER TABLE firm_knowledge ADD CONSTRAINT firm_knowledge_file_type_check
    CHECK (file_type IN ('pdf','docx','txt','note'));
