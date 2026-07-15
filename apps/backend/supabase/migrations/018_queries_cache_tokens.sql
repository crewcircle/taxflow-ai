-- Task C5 / B1: persist Anthropic prompt-cache token usage on the queries row.
--
-- run()/run_stream() now surface usage.cache_read_input_tokens and
-- usage.cache_creation_input_tokens (Task B1). Both the POST /query and the SSE
-- /query/stream paths write them so before/after cost claims can account for
-- cache-read tokens (billed at ~10% of input price).
ALTER TABLE queries ADD COLUMN cache_read_input_tokens integer;
ALTER TABLE queries ADD COLUMN cache_creation_input_tokens integer;
