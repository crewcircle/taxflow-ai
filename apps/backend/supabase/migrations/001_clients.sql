CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE clients (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_name text NOT NULL,
    business_type text NOT NULL CHECK (business_type IN (
        'dental','gp','specialist','pharmacy','physio','chiro','legal',
        'accounting','financial_advice','property','construction','hospitality','retail','other'
    )),
    email text UNIQUE NOT NULL,
    abn text,
    suburb text NOT NULL,
    state text NOT NULL CHECK (state IN ('NSW','VIC','QLD','WA','SA','TAS','ACT','NT')),
    postcode text,
    phone text,
    firm_size_staff integer,
    stripe_customer_id text UNIQUE,
    stripe_subscription_id text UNIQUE,
    subscription_status text NOT NULL DEFAULT 'trialing' CHECK (subscription_status IN (
        'trialing','active','past_due','cancelled','paused'
    )),
    tier text NOT NULL DEFAULT 'professional' CHECK (tier IN ('starter','professional','practice','enterprise')),
    gbp_access_token text,
    gbp_refresh_token text,
    gbp_location_id text,
    voice_sample text,
    firm_style jsonb DEFAULT '{}'::jsonb,
    active_modules text[] DEFAULT '{research}'::text[],
    do_not_contact boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz
);
