# TaxFlow AI — Manual Account Setup Runbook

Complete these in order. Each step ends with exactly what to hand back to Claude
so the rest of the pipeline (Doppler secrets / DNS / Coolify / Supabase migrations)
can be wired up automatically. Total time: roughly 45-90 minutes, most of it waiting
on DNS propagation and Stripe business verification.

Do this from a browser where you're comfortable being logged into GitHub as the
`crewcircle` account (or logging in fresh with `crewcircle@zohomail.com.au`).

---

## 0. Prerequisites

- Access to the `crewcircle@zohomail.com.au` inbox (every service sends a verification email here)
- Access to crazydomains.com.au login for `crewcircle.com.au`
- A business credit/debit card for DigitalOcean ($24/mo droplet) and Stripe (no cost to register)
- Your ABN (Australian Business Number) for Stripe

---

## 1. Cloudflare (DNS + CDN)

1. Go to https://dash.cloudflare.com/sign-up
2. Click **Sign in with GitHub** → authorize
3. Complete account setup with email `crewcircle@zohomail.com.au` if prompted
4. Click **Add a Site** → enter `crewcircle.com.au` → select **Free plan** → skip the DNS scan (Continue)
5. Note the **two nameservers** shown (format `xxx.ns.cloudflare.com`) — needed for Step 7 (Crazy Domains)
6. Go to **My Profile → API Tokens → Create Token**
   - Use template **"Edit zone DNS"**
   - Zone Resources: **Include → Specific zone → crewcircle.com.au**
   - Continue → Create Token → **copy the token now** (shown once)
7. Go to the `crewcircle.com.au` zone overview → copy the **Zone ID** from the right sidebar

**Hand back to Claude:**
```
CLOUDFLARE_API_TOKEN=<token>
CLOUDFLARE_ZONE_ID=<zone id>
CLOUDFLARE_NS1=<nameserver 1>
CLOUDFLARE_NS2=<nameserver 2>
```

---

## 2. Crazy Domains — Nameserver Cutover (the "manual DNS step")

This is the one step with no API — it must be done in the Crazy Domains UI.

1. Log in to https://www.crazydomains.com.au with the account that owns `crewcircle.com.au`
2. Go to **My Account → Domain Names → crewcircle.com.au → Manage DNS → Nameservers**
3. Replace the existing (Crazy Domains default) nameservers with the two Cloudflare
   nameservers from Step 1.6 above
4. Save changes

Propagation takes 15-30 minutes typically, up to 3 hours. No further action needed —
once it propagates, Cloudflare's dashboard will show the zone status change from
"Pending" to "Active" on its own.

**Hand back to Claude:** just say "DNS cutover done" — no values to copy.

---

## 3. DigitalOcean (backend hosting droplet)

1. Go to https://cloud.digitalocean.com/registrations/new
2. Click **Sign up with GitHub** → authorize
3. Complete billing setup (credit card required)
4. Go to **API → Personal access tokens → Generate New Token**
   - Name: `taxflow-automation`, Expiration: **No expiry**, Scope: **Read + Write**
   - Copy the token now (shown once)
5. Go to **Droplets → Create Droplet**:
   - Region: **Sydney (syd1)**
   - OS: **Ubuntu 24.04 (LTS) x64**
   - Size: Basic → Regular → **4GB RAM / 2 vCPU / 80GB SSD** (~$24/month)
   - Authentication: SSH Keys → add a key. If you don't have one:
     ```
     ssh-keygen -t ed25519 -C "taxflow" -f ~/.ssh/id_ed25519 -N ""
     cat ~/.ssh/id_ed25519.pub
     ```
     paste the output into the DigitalOcean SSH key field
   - Hostname: `taxflow-prod`
   - Tags: `taxflow`, `production`
6. Create the droplet, wait for status **Active**, copy the public IPv4 address

**Hand back to Claude:**
```
DIGITALOCEAN_TOKEN=<dop_v1_...>
DROPLET_IP=<x.x.x.x>
```

---

## 4. Supabase (database)

1. Go to https://supabase.com/dashboard/sign-in
2. Click **Continue with GitHub** → authorize
3. Organization setup: name it `crewcircle`, type: personal
4. Go to **Account → Access Tokens → Generate new token**
   - Name: `taxflow-automation`, no expiry — copy it now (shown once)
5. Note your **Organization ID** from the URL: `https://supabase.com/dashboard/org/<ORG_ID>/settings`

You do NOT need to manually create the project — once you hand back these two values,
Claude can create the `taxflow-prod` project via the Supabase Management API and run
the 8 migrations that are already written and tested in this repo
(`apps/backend/supabase/migrations/`).

**Hand back to Claude:**
```
SUPABASE_ACCESS_TOKEN=<sbp_...>
SUPABASE_ORG_ID=<org id>
```

---

## 5. Doppler (secrets manager)

1. Go to https://dashboard.doppler.com/login
2. Click **Continue with GitHub** → authorize
3. On first login, set workspace name to `crewcircle`
4. Go to **Projects → Create Project**: name `crewcircle-master`, a `prd` config is auto-created
5. Go to **Settings → Service Accounts → Add Service Account**: name `automation`, role `Manager`
6. Open the `automation` service account → **Add Token**: name `cli-automation`, no expiry
   — copy the token now (shown once, format `dp.pt.xxxxx`)

**Hand back to Claude:**
```
DOPPLER_TOKEN=<dp.pt....>
```

Once you're on Doppler, Claude can programmatically create the `taxflow` project and
seed every secret gathered in this runbook via the Doppler CLI — you won't need to
paste tokens into multiple places by hand.

*(If you'd rather skip Doppler entirely for now and just use local `.env` files, say so —
it's not a hard dependency to get the dev servers running, only for the production deploy.)*

---

## 6. Stripe (billing) — do this one carefully, it's a real business account

1. Go to https://dashboard.stripe.com/register
2. Sign up with email `crewcircle@zohomail.com.au`, full name, country **Australia**
3. Verify the email (check the Zoho inbox, click the link)
4. In the dashboard: Business type **Company**, Company name **CREW CIRCLE PTY LTD**,
   enter your **ABN**, Industry **Software / Technology**
5. Go to **Developers → API Keys**:
   - Reveal the **live secret key** (`sk_live_...`) — copy it
   - Note the **publishable key** (`pk_live_...`)
6. Go to **Products → Add Product** and create 3 products:
   - "TaxFlow Starter" — $2,400/yr AUD, recurring
   - "TaxFlow Professional" — $6,000/yr AUD, recurring
   - "TaxFlow Practice" — $12,000/yr AUD, recurring
7. Go to **Developers → Webhooks → Add endpoint**:
   - URL: `https://api.taxflow.crewcircle.com.au/webhooks/stripe`
   - Events: `customer.subscription.created`, `customer.subscription.updated`,
     `customer.subscription.deleted`, `customer.subscription.trial_will_end`,
     `invoice.payment_failed`, `invoice.paid`, `payment_method.attached`
   - Copy the **signing secret** (`whsec_...`)
8. Go to **Settings → Tax**: enable Stripe Tax, add Australia → GST 10%

Note: this webhook URL won't resolve until the backend is actually deployed (Week 4
in the plan) — that's fine, add it now anyway so the secret exists.

**Hand back to Claude:**
```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_STARTER_PRICE_ID=price_...
STRIPE_PROFESSIONAL_PRICE_ID=price_...
STRIPE_PRACTICE_PRICE_ID=price_...
```

---

## 7. OpenAI (embeddings — needed for the knowledge base pipeline)

1. Go to https://platform.openai.com/signup and create an account (or sign in)
2. Add a payment method (embeddings for the full corpus cost roughly $5 one-time)
3. Go to **API keys → Create new secret key**

**Hand back to Claude:**
```
OPENAI_API_KEY=sk-...
```

---

## 8. Anthropic (the LLM powering every agent)

1. Go to https://console.anthropic.com and sign in / create an account
2. Add a payment method
3. Go to **API Keys → Create Key**

**Hand back to Claude:**
```
ANTHROPIC_API_KEY=sk-ant-...
```

---

## 9. Xero App Marketplace + CPA Australia partner applications (Week 5 item, not urgent now)

These are longer-form partner applications, not API signups — do these later, they're
not required to get the product running:
- Xero: https://developer.xero.com/app-marketplace/ → "Become a partner"
- CPA Australia: https://www.cpaaustralia.com.au (partner/affiliate program page)

---

## What happens after you hand back the values above

Paste the collected `KEY=value` pairs back into the chat (all at once or as you finish
each section) and Claude will:
1. Set up Doppler (or local `.env` files) with all of them
2. Create the Supabase project and run the 8 tested migrations
3. Point Cloudflare DNS at Vercel (dashboard) and the DigitalOcean droplet (API)
4. Install Coolify on the droplet and deploy the backend container
5. Deploy the dashboard to Vercel
6. Run the Week 1 verification checklist end-to-end

None of your actual credentials need to be typed anywhere except directly into each
service's own signup page — you're only ever pasting back the resulting API tokens,
never a password.
