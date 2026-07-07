CREATE TABLE regulatory_alerts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source text NOT NULL,
    alert_type text NOT NULL,
    title text NOT NULL,
    summary text,
    effective_date date,
    url text,
    affected_client_types text[],
    draft_comms_md text,
    processed boolean NOT NULL DEFAULT false,
    detected_at timestamptz NOT NULL DEFAULT now()
);
