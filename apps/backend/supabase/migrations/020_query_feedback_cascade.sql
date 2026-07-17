-- Task C5 follow-up: cascade query_feedback when its parent query is deleted.
--
-- 017_query_feedback.sql declared query_feedback.query_id REFERENCES queries(id)
-- with no ON DELETE behaviour (i.e. RESTRICT). The nightly demo reset
-- (services/demo_reset.py) deletes demo clients' queries, so any feedback rows
-- attached to those queries would raise a FK violation and abort the reset.
-- Make the FK cascade so deleting a query cleans up its feedback.

ALTER TABLE query_feedback
    DROP CONSTRAINT query_feedback_query_id_fkey;

ALTER TABLE query_feedback
    ADD CONSTRAINT query_feedback_query_id_fkey
    FOREIGN KEY (query_id) REFERENCES queries(id) ON DELETE CASCADE;
