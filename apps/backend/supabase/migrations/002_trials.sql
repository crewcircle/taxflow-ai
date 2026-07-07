CREATE TABLE trials (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    trial_started_at timestamptz NOT NULL DEFAULT now(),
    trial_ends_at timestamptz NOT NULL DEFAULT (now() + interval '30 days'),
    trial_status text NOT NULL DEFAULT 'active' CHECK (trial_status IN ('active','converted','expired','cancelled')),
    card_collected_at timestamptz,
    converted_at timestamptz,
    queries_used integer NOT NULL DEFAULT 0,
    queries_cap integer NOT NULL DEFAULT 100,
    docs_used integer NOT NULL DEFAULT 10,
    docs_cap integer NOT NULL DEFAULT 10
);

CREATE OR REPLACE FUNCTION increment_trial_usage(p_client_id uuid, p_metric text)
RETURNS void AS $$
DECLARE
    v_trial_id uuid;
BEGIN
    SELECT id INTO v_trial_id
    FROM trials
    WHERE client_id = p_client_id
    ORDER BY trial_started_at DESC
    LIMIT 1
    FOR UPDATE;

    IF v_trial_id IS NULL THEN
        RETURN;
    END IF;

    IF p_metric = 'queries' THEN
        UPDATE trials SET queries_used = queries_used + 1 WHERE id = v_trial_id;
    ELSIF p_metric = 'docs' THEN
        UPDATE trials SET docs_used = docs_used + 1 WHERE id = v_trial_id;
    END IF;
END;
$$ LANGUAGE plpgsql;
