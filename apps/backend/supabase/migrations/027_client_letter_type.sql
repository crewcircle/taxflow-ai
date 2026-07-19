-- Client letter: a client-facing document type, deliberately distinct from
-- advice_memo (internal working paper) rather than merged into one export -
-- the two carry different professional sign-off obligations.
ALTER TABLE documents DROP CONSTRAINT documents_document_type_check;
ALTER TABLE documents ADD CONSTRAINT documents_document_type_check
    CHECK (document_type IN (
        'advice_memo','ato_response','remission_request','objection_letter',
        'private_ruling_application','engagement_letter','payg_variation',
        'fbt_declaration','client_letter'
    ));
