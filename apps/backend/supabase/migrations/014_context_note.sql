-- Short "why this was asked / what's next" line shown alongside demo history,
-- so the seeded activity reads as an ongoing engagement rather than a
-- one-off snapshot. Nullable - real (non-demo) rows leave it unset.
alter table queries add column if not exists context_note text;
alter table documents add column if not exists context_note text;
