-- First-class conversation threads. query_sessions (028) was label-only,
-- created lazily on first rename - so most sessions had no row at all, and
-- a thread was never attributable to a real engagement/end-client except
-- transitively through whatever engagement_id each individual queries row
-- happened to carry (which, per Phase 2, may now differ turn-to-turn or be
-- absent on historical rows).
ALTER TABLE query_sessions ADD COLUMN engagement_id uuid REFERENCES engagements(id);
ALTER TABLE query_sessions ADD COLUMN firm_client_id uuid REFERENCES firm_clients(id);

-- queries.session_id (019) has never had a real FK to query_sessions - only a
-- bare uuid matched by convention. Add it now that the app layer creates a
-- query_sessions row eagerly (on the FIRST query of a session, not only on
-- rename), so the constraint will actually hold going forward.
--
-- NOT VALID skips scanning/validating existing rows at ALTER time (cheap,
-- no table lock beyond the brief DDL), so this migration alone cannot fail
-- or block on current data. The historical backfill (scripts/backfill_
-- query_sessions.py) must run and reach 100% coverage BEFORE a separate
-- follow-up `ALTER TABLE queries VALIDATE CONSTRAINT queries_session_id_fkey`
-- is safe to run - that step is deliberately NOT part of this migration.
ALTER TABLE queries ADD CONSTRAINT queries_session_id_fkey
    FOREIGN KEY (session_id) REFERENCES query_sessions(session_id) NOT VALID;
