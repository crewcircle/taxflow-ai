-- Short topic label per question (e.g. "GST margin scheme"), used to render
-- clickable scenario tags that jump to the related past question. Nullable -
-- real (non-demo) queries leave it unset.
alter table queries add column if not exists topic_tag text;
