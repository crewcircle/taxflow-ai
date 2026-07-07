ALTER TABLE clients ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON clients USING (auth.role() = 'service_role');

ALTER TABLE trials ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON trials USING (auth.role() = 'service_role');

ALTER TABLE knowledge_chunks ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON knowledge_chunks USING (auth.role() = 'service_role');

ALTER TABLE queries ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON queries USING (auth.role() = 'service_role');

ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON documents USING (auth.role() = 'service_role');

ALTER TABLE firm_knowledge ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON firm_knowledge USING (auth.role() = 'service_role');

ALTER TABLE regulatory_alerts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON regulatory_alerts USING (auth.role() = 'service_role');
