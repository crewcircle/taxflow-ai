CREATE TABLE queries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid NOT NULL REFERENCES clients(id),
    user_email text NOT NULL,
    question text NOT NULL,
    module text NOT NULL CHECK (module IN ('research','ato_correspondence','document','regulatory_monitor')),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processing','completed','failed')),
    pipeline_outputs jsonb DEFAULT '{}'::jsonb,
    final_answer text,
    citations jsonb DEFAULT '[]'::jsonb,
    confidence_score numeric(3,2),
    model_used text,
    input_tokens integer,
    output_tokens integer,
    wall_time_ms integer,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);
