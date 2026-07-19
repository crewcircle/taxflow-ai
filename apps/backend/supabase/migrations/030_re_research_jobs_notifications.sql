-- Task C1: async feedback re-research job queue + user notifications.
--
-- When a user leaves a thumbs-down WITH a note on an answer, the feedback
-- endpoint (C2) enqueues a re_research_jobs row so a background worker can
-- re-run the answer with the stated issue as steering. feedback_note is
-- snapshotted at enqueue so the worker has the user's stated problem without a
-- second read. UNIQUE(feedback_id) + ON CONFLICT DO NOTHING makes enqueue
-- at-most-once; claim_next()'s FOR UPDATE SKIP LOCKED + status='running' makes
-- concurrent execution at-most-once.
--
-- RLS mirrors 017_query_feedback.sql / 008_rls.sql: a single
-- service_role_full_access policy (auth.role() = 'service_role'); per-client
-- isolation is enforced by explicit WHERE client_id = %s predicates in the repo.

CREATE TABLE re_research_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid NOT NULL REFERENCES clients(id),
    query_id uuid NOT NULL REFERENCES queries(id),
    feedback_id uuid NOT NULL UNIQUE REFERENCES query_feedback(id),
    feedback_note text,
    trigger text NOT NULL DEFAULT 'thumbs_down',
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'done', 'failed')),
    original_answer text,
    error_message text,
    attempts int NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_re_research_jobs_claim ON re_research_jobs (status, next_attempt_at);

ALTER TABLE re_research_jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON re_research_jobs USING (auth.role() = 'service_role');


CREATE TABLE notifications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid NOT NULL REFERENCES clients(id),
    kind text NOT NULL,
    query_id uuid REFERENCES queries(id),
    title text,
    body text,
    read_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_notifications_client ON notifications (client_id, created_at DESC);

ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access" ON notifications USING (auth.role() = 'service_role');


ALTER TABLE queries ADD COLUMN re_research_status text;
