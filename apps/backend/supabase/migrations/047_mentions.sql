-- Staff @mentions: tag a colleague in a comment thread and they get a
-- reminder in the notification bell.
--
-- annotations.author_user_id: real per-user identity for a comment, now that
-- 043 gives firms individual logins - author_name (free text) predates this
-- and stays for historical display, exactly like engagements.created_by (039).
-- mentioned_user_ids: the users tagged in this comment's body via
-- @[Display Name](user_id) tokens, parsed server-side on create/reply.
--
-- notifications.recipient_user_id: nullable so every existing notification
-- kind (answer_improved, re_research_failed, regulatory alerts) keeps its
-- current "visible to the whole firm" behaviour untouched (NULL = firm-wide).
-- A mention notification sets this to the specific tagged user, and the same
-- column is the general mechanism for any future "this needs a specific
-- person's attention" notification (approval needed, clarification asked),
-- not just @mentions.
ALTER TABLE annotations   ADD COLUMN author_user_id uuid REFERENCES users(id);
ALTER TABLE annotations   ADD COLUMN mentioned_user_ids uuid[];
ALTER TABLE notifications ADD COLUMN recipient_user_id uuid REFERENCES users(id);

CREATE INDEX idx_notifications_recipient ON notifications (client_id, recipient_user_id, created_at DESC);
