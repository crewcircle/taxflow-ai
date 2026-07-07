# TaxFlow AI - Phase 1 Detailed Implementation Plan

## Constraints and Fixed Facts

```
Domain registered      : crewcircle.com.au (at Crazy Domains)
App subdomain          : taxflow.crewcircle.com.au
API subdomain          : api.taxflow.crewcircle.com.au
System email           : crewcircle@zohomail.com.au
GitHub account         : exists, registered with crewcircle@zohomail.com.au
GitHub SSO available   : Supabase, Doppler, Sentry, Vercel, Cloudflare (via OAuth)
No existing infra      : fresh start on everything below GitHub
AI execution           : Claude Code for all engineering, Browser Use for signups
Supervision            : none required - every step self-verifies
```

## Phase 1 Scope

6 weeks. Day-by-day. Output: 10 paying firms, AUD $60,000 ARR.

Week 1: Infrastructure + accounts + monorepo + knowledge base ingestion
Week 2: Research Agent (Module 1) passing accuracy gate
Week 3: Draft Agent + Verify Agent + ATO Correspondence (Module 2)
Week 4: Dashboard, Stripe live, 3 paying reference firms
Week 5: Module 3 full, 10 paying firms, Xero application submitted
Week 6: Referral system, content flywheel, 30-trial pipeline

---

# WEEK 1: INFRASTRUCTURE FROM SCRATCH

## Prerequisites Check (Day 0 - before anything starts)

Run this block first. Every item must pass before Day 1 begins.

```bash
# Verify GitHub account exists and CLI is authenticated
gh auth status
# Expected: Logged in to github.com as <username>

# Verify domain is registered and DNS is currently at Crazy Domains
dig NS crewcircle.com.au +short
# Expected: returns Crazy Domains nameservers (e.g. ns1.crazydomains.com)

# Verify system email works
curl -s "https://api.zohomail.com" | head -1
# Just confirms network. Actual email test: send a test email from crewcircle@zohomail.com.au
# to itself and confirm receipt in Zoho inbox.

# Confirm what tools exist locally
which node && node --version    # need 20+
which python3 && python3 --version  # need 3.11+
which pulumi && pulumi version  # install if missing
which doppler && doppler --version  # install if missing
```

Install missing tools:
```bash
# Pulumi
curl -fsSL https://get.pulumi.com | sh && export PATH=$PATH:$HOME/.pulumi/bin

# Doppler CLI
(curl -Ls --tlsv1.2 --proto "=https" --retry 3 https://cli.doppler.com/install.sh || wget -t 3 -qO- https://cli.doppler.com/install.sh) | sudo sh

# uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# pnpm
npm install -g pnpm

# Verify all
pulumi version && doppler --version && uv --version && pnpm --version
```

---

## DAY 1: Cloudflare + GitHub Repo + Monorepo Scaffold

### Step 1.1 - Create Cloudflare Account (GitHub SSO)

Cloudflare supports "Sign in with GitHub". This ties the Cloudflare account to the GitHub account already created.

```bash
# Browser Use agent does this. The AGENT.md for Browser Use:
cat > /tmp/cloudflare_signup.md << 'EOF'
# Browser Use Task: Create Cloudflare Account

1. Navigate to https://dash.cloudflare.com/sign-up
2. Click "Sign in with GitHub" button
3. Authorize Cloudflare to access the GitHub account
4. Complete account setup with email crewcircle@zohomail.com.au if prompted
5. On the Cloudflare dashboard, click "Add a Site"
6. Enter domain: crewcircle.com.au
7. Select Free plan
8. Skip the DNS scan (click Continue)
9. Note the TWO nameservers shown (format: xxx.ns.cloudflare.com)
10. Navigate to My Profile > API Tokens > Create Token
11. Use template "Edit zone DNS"
12. Set Zone Resources to: Include > Specific zone > crewcircle.com.au
13. Click Continue to summary > Create Token
14. COPY the token value - shown only once
15. Navigate to the crewcircle.com.au zone overview
16. Copy the Zone ID from the right sidebar
17. Output: CLOUDFLARE_API_TOKEN=<token>, CLOUDFLARE_ZONE_ID=<zone_id>, NS1=<ns1>, NS2=<ns2>
EOF
# Run: browser-use --task-file /tmp/cloudflare_signup.md
```

Verification (run after Browser Use completes):
```bash
export CLOUDFLARE_API_TOKEN="<token-from-browser-use>"
export CLOUDFLARE_ZONE_ID="<zone-id-from-browser-use>"

# Verify token is valid and has correct permissions
curl -s -X GET "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['success'] == True, f'Cloudflare API failed: {d}'
assert d['result']['name'] == 'crewcircle.com.au', 'Wrong zone'
print('PASS: Cloudflare zone verified - crewcircle.com.au')
print(f'Zone ID: {d[\"result\"][\"id\"]}')
print(f'Status: {d[\"result\"][\"status\"]}')
"
```

### Step 1.2 - Update Nameservers at Crazy Domains (Human Step - 5 minutes)

This is the only human step in Week 1. It cannot be automated because Crazy Domains does not have an API.

```
Manual action required:
1. Log in to crazydomains.com.au with the account that owns crewcircle.com.au
2. Go to My Account > Domain Names > crewcircle.com.au > Manage DNS > Nameservers
3. Change nameservers from Crazy Domains defaults to the two Cloudflare nameservers
   noted in Step 1.1 (format: xxx.ns.cloudflare.com and yyy.ns.cloudflare.com)
4. Save changes
```

Verification (run after saving, DNS propagation takes 5-30 minutes):
```bash
# Poll until Cloudflare nameservers appear. This loop exits when propagation completes.
for i in $(seq 1 36); do
  NS=$(dig NS crewcircle.com.au +short @8.8.8.8)
  if echo "$NS" | grep -q "cloudflare.com"; then
    echo "PASS: Nameservers updated to Cloudflare"
    echo "$NS"
    break
  fi
  echo "Attempt $i/36: nameservers not yet propagated, waiting 5 minutes..."
  sleep 300
done
# If loop exits without PASS, nameserver change has not propagated yet.
# Maximum wait: 3 hours. Typical: 15-30 minutes.
```

Also verify in Cloudflare dashboard: zone status should change from "Pending" to "Active".
```bash
curl -s -X GET "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | python3 -c "
import json,sys
d=json.load(sys.stdin)
status=d['result']['status']
print(f'Zone status: {status}')
assert status == 'active', f'Expected active, got {status}. Wait longer.'
print('PASS: Cloudflare zone is active')
"
```

### Step 1.3 - Create Subdomains in Cloudflare DNS

Now that Cloudflare controls crewcircle.com.au DNS, create the DNS records for TaxFlow.
These point to Vercel (frontend) and a DigitalOcean droplet (backend). The droplet IP
is not known yet - we use a placeholder 1.1.1.1 and update it on Day 2 after droplet creation.

```bash
# Create taxflow.crewcircle.com.au CNAME to Vercel
curl -s -X POST "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{
    "type": "CNAME",
    "name": "taxflow",
    "content": "cname.vercel-dns.com",
    "proxied": true
  }' | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['success'], f'DNS record creation failed: {d[\"errors\"]}'
print(f'PASS: taxflow.crewcircle.com.au CNAME created, record ID: {d[\"result\"][\"id\"]}')
"

# Create api.taxflow.crewcircle.com.au A record (placeholder IP, updated Day 2)
curl -s -X POST "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{
    "type": "A",
    "name": "api.taxflow",
    "content": "1.1.1.1",
    "proxied": true,
    "comment": "placeholder - update with DigitalOcean droplet IP on Day 2"
  }' | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['success'], f'DNS record creation failed: {d[\"errors\"]}'
print(f'PASS: api.taxflow.crewcircle.com.au A record created (placeholder IP)')
print(f'Record ID: {d[\"result\"][\"id\"]} - SAVE THIS to update with real IP on Day 2')
"

# List all DNS records to confirm
curl -s "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for r in d['result']:
    print(f'{r[\"type\"]:6} {r[\"name\"]:45} -> {r[\"content\"]}')
"
```

### Step 1.4 - GitHub Repository and Monorepo Scaffold

```bash
# Create private GitHub repo using GitHub CLI (already authenticated)
gh repo create taxflow-ai \
  --private \
  --description "TaxFlow AI - AI workflow intelligence for Australian accounting firms" \
  --gitignore Python \
  --clone

cd taxflow-ai

# Verify clone worked
git status
# Expected: On branch main, nothing to commit

# Create monorepo structure
mkdir -p apps/backend
mkdir -p apps/dashboard
mkdir -p packages/knowledge
mkdir -p packages/agents
mkdir -p packages/shared
mkdir -p infra/pulumi
mkdir -p .github/workflows

# Root package.json for pnpm workspaces
cat > package.json << 'EOF'
{
  "name": "taxflow-ai",
  "private": true,
  "workspaces": ["apps/*", "packages/*"],
  "scripts": {
    "dev": "turbo run dev",
    "build": "turbo run build",
    "test": "turbo run test",
    "lint": "turbo run lint"
  },
  "devDependencies": {
    "turbo": "^2.0.0"
  },
  "packageManager": "pnpm@9.0.0"
}
EOF

cat > turbo.json << 'EOF'
{
  "$schema": "https://turbo.build/schema.json",
  "tasks": {
    "build": {"dependsOn": ["^build"], "outputs": [".next/**", "dist/**"]},
    "dev":   {"cache": false, "persistent": true},
    "test":  {"dependsOn": ["^build"]},
    "lint":  {}
  }
}
EOF

# Root .gitignore additions (Python + Next.js)
cat >> .gitignore << 'EOF'
.env.local
.env.*.local
.env.master
*.env
__pycache__/
*.py[cod]
.venv/
node_modules/
.next/
.turbo/
*.pulumi.yaml.bak
.doppler/
EOF

# Commit scaffold
git add .
git commit -m "chore: monorepo scaffold - pnpm workspaces + turbo"
git push origin main

# Verify push
gh repo view taxflow-ai --json name,visibility,pushedAt | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['visibility'] == 'PRIVATE', 'Repo should be private'
print(f'PASS: github.com repo {d[\"name\"]} is PRIVATE, last push: {d[\"pushedAt\"]}')
"
```

### Step 1.5 - Doppler Account (GitHub SSO) and Master Project

Doppler is the secrets manager. The master project holds credentials shared across all
sub-projects. TaxFlow gets its own Doppler project inheriting from master.

```bash
# Browser Use agent creates Doppler account via GitHub SSO
cat > /tmp/doppler_signup.md << 'EOF'
# Browser Use Task: Create Doppler Account

1. Navigate to https://dashboard.doppler.com/login
2. Click "Continue with GitHub"
3. Authorize Doppler application
4. On first login, set workplace name to: crewcircle
5. Navigate to Projects > Create Project
6. Project name: crewcircle-master, description: Shared credentials for all apps
7. Click into crewcircle-master > Environments: a "prd" config is auto-created
8. Navigate to Settings > Service Accounts > Add Service Account
9. Name: automation, Role: Manager
10. Navigate to the automation service account > Add Token
11. Name: cli-automation, No expiry
12. COPY the token (shown once): dp.pt.xxxxx
13. Navigate to Workplace Settings > Service Tokens
14. Also create a workplace-level token if available, else the service account token covers API access
15. Output: DOPPLER_TOKEN=<dp.pt.xxxxx>
EOF
```

After Browser Use, bootstrap Doppler CLI and create TaxFlow project:
```bash
export DOPPLER_TOKEN="<token-from-browser-use>"

# Authenticate CLI with the token
doppler configure set token $DOPPLER_TOKEN --scope /

# Verify authentication
doppler whoami
# Expected: Outputs the authenticated user/service-account name

# Create taxflow project
doppler projects create taxflow --description "TaxFlow AI application secrets"

# Doppler auto-creates dev, stg, prd environments. Verify:
doppler environments --project taxflow
# Expected: dev, stg, prd listed

# Seed initial secrets into taxflow/prd
# These are the keys the app needs - values filled as each account is created
doppler secrets upload --project taxflow --config prd << 'EOF'
ENVIRONMENT=production
APP_NAME=taxflow
BASE_DOMAIN=crewcircle.com.au
APP_SUBDOMAIN=taxflow.crewcircle.com.au
API_SUBDOMAIN=api.taxflow.crewcircle.com.au
SYSTEM_EMAIL=crewcircle@zohomail.com.au
EOF

# Verify secrets are set
doppler secrets --project taxflow --config prd
# Expected: lists ENVIRONMENT, APP_NAME, BASE_DOMAIN, etc.

# Create a service token for the backend app to use at runtime
doppler configs tokens create prd-runtime \
  --project taxflow \
  --config prd \
  --max-age 0 \
  --output json | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(f'PASS: Runtime service token created')
print(f'Token: {d[\"key\"]}')
print('SAVE this token - it goes into DigitalOcean droplet env on Day 2')
"
```

### Step 1.6 - GitHub Actions CI Pipeline

```bash
cd ~/taxflow-ai

cat > .github/workflows/ci.yml << 'EOF'
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test-backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_PASSWORD: testpassword
          POSTGRES_DB: taxflow_test
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh && echo "$HOME/.cargo/bin" >> $GITHUB_PATH

      - name: Install backend dependencies
        working-directory: apps/backend
        run: uv sync

      - name: Run backend tests
        working-directory: apps/backend
        env:
          DATABASE_URL: postgresql://postgres:testpassword@localhost:5432/taxflow_test
          ENVIRONMENT: test
        run: uv run pytest tests/ -v --tb=short

  test-dashboard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with:
          version: 9
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: "pnpm"
      - run: pnpm install
      - name: Typecheck dashboard
        working-directory: apps/dashboard
        run: pnpm typecheck
      - name: Lint dashboard
        working-directory: apps/dashboard
        run: pnpm lint
EOF

git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions pipeline for backend pytest + dashboard typecheck"
git push

# Verify CI triggered
sleep 10
gh run list --repo taxflow-ai --limit 3
# Expected: A run in_progress or completed for the commit just pushed
```

### End of Day 1 Verification Checklist

```bash
cat << 'CHECKLIST'
Run each command. All must output PASS.

1. Cloudflare zone active:
CHECKLIST

# 1. Cloudflare
curl -s "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print('PASS' if d['result']['status']=='active' else 'FAIL', 'Cloudflare zone')"

# 2. Nameservers
dig NS crewcircle.com.au +short | grep -q "cloudflare" && echo "PASS: nameservers" || echo "FAIL: nameservers not yet Cloudflare"

# 3. DNS records exist
curl -s "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | python3 -c "
import json,sys
d=json.load(sys.stdin)
names=[r['name'] for r in d['result']]
checks=['taxflow.crewcircle.com.au','api.taxflow.crewcircle.com.au']
for c in checks:
    print('PASS' if c in names else 'FAIL', f'DNS record {c}')
"

# 4. GitHub repo
gh repo view taxflow-ai --json visibility | python3 -c "import json,sys; d=json.load(sys.stdin); print('PASS' if d['visibility']=='PRIVATE' else 'FAIL', 'GitHub repo private')"

# 5. Doppler project
doppler projects get taxflow | grep -q "taxflow" && echo "PASS: Doppler project" || echo "FAIL: Doppler project"

# 6. CI pipeline exists
ls .github/workflows/ci.yml && echo "PASS: CI workflow file" || echo "FAIL: CI workflow missing"
```

---

## DAY 2: DigitalOcean Droplet + Coolify + Supabase

### Step 2.1 - DigitalOcean Account and Droplet

```bash
# Browser Use creates DigitalOcean account via GitHub SSO
cat > /tmp/digitalocean_signup.md << 'EOF'
# Browser Use Task: DigitalOcean Account + Droplet

1. Navigate to https://cloud.digitalocean.com/registrations/new
2. Click "Sign up with GitHub"
3. Authorize DigitalOcean OAuth app
4. Complete billing setup (credit card required - manual step, pause here)
5. After billing: navigate to API > Personal access tokens > Generate New Token
6. Name: taxflow-automation, Expiration: No expiry, Scope: Read + Write
7. COPY the token: dop_v1_xxxxx
8. Navigate to Droplets > Create Droplet
9. Settings:
   - Region: Sydney (syd1)
   - OS: Ubuntu 24.04 (LTS) x64
   - Size: Basic > Regular > 4GB RAM / 2 vCPU / 80GB SSD ($24/month)
   - Authentication: SSH Keys > Add SSH key (paste the output of: cat ~/.ssh/id_rsa.pub)
     If no SSH key exists, run: ssh-keygen -t ed25519 -C "taxflow" -f ~/.ssh/id_ed25519 -N ""
     Then paste content of: cat ~/.ssh/id_ed25519.pub
   - Hostname: taxflow-prod
   - Tags: taxflow, production
10. Create droplet. Wait for status: Active
11. Copy the public IPv4 address
12. Output: DO_API_TOKEN=<dop_v1_xxxxx>, DROPLET_IP=<x.x.x.x>
EOF
```

After Browser Use completes, store credentials and update DNS:
```bash
export DO_API_TOKEN="<token-from-browser-use>"
export DROPLET_IP="<ip-from-browser-use>"

# Store in Doppler
doppler secrets set \
  DIGITALOCEAN_TOKEN="$DO_API_TOKEN" \
  DROPLET_IP="$DROPLET_IP" \
  --project taxflow --config prd

# Verify droplet is reachable
ping -c 3 $DROPLET_IP
# Expected: 3 packets transmitted, 3 received

# SSH verify (uses the key created during signup)
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 root@$DROPLET_IP "echo PASS: SSH to droplet works && uname -a"
# Expected: PASS: SSH to droplet works + Linux hostname ...

# Update Cloudflare api.taxflow.crewcircle.com.au A record with real IP
# First get the record ID (saved in Step 1.3 output, or fetch it now)
RECORD_ID=$(curl -s "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records?name=api.taxflow.crewcircle.com.au" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print(d['result'][0]['id'])")

curl -s -X PATCH "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records/$RECORD_ID" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data "{\"content\": \"$DROPLET_IP\"}" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['success'], f'DNS update failed: {d}'
print(f'PASS: api.taxflow.crewcircle.com.au updated to {d[\"result\"][\"content\"]}')
"
```

### Step 2.2 - Install Coolify on Droplet

Coolify is the self-hosted PaaS. It runs on the droplet and manages Docker containers,
reverse proxy (Traefik), and SSL certificates automatically via Let's Encrypt.

```bash
# Install Coolify via its official one-line installer
ssh root@$DROPLET_IP << 'REMOTE'
set -e

# Update system
apt-get update -qq && apt-get upgrade -y -qq

# Install Coolify
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash

# Wait for Coolify services to start
sleep 30

# Verify Coolify is running
systemctl status coolify
docker ps | grep coolify

echo "PASS: Coolify installed"
REMOTE

# Verify Coolify UI is reachable (it runs on port 8000 by default)
curl -s -o /dev/null -w "%{http_code}" http://$DROPLET_IP:8000
# Expected: 200 or 302 (redirect to login)
# If 000, Coolify is still starting - wait 60 seconds and retry

echo "Coolify dashboard at: http://$DROPLET_IP:8000"
echo "Complete initial setup in browser:"
echo "  1. Navigate to http://$DROPLET_IP:8000"
echo "  2. Create admin account (email: crewcircle@zohomail.com.au, strong password)"
echo "  3. Set instance domain to: coolify.crewcircle.com.au (optional, can skip)"
echo "  4. Connect GitHub: Settings > Source Control > GitHub > Authorize"
echo "  5. Add the taxflow-ai repository"
```

Add Coolify subdomain to Cloudflare DNS (optional but useful for access):
```bash
curl -s -X POST "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data "{\"type\":\"A\",\"name\":\"coolify\",\"content\":\"$DROPLET_IP\",\"proxied\":false}" | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print('PASS' if d['success'] else 'FAIL', 'Coolify DNS record')"
# Note: proxied=false for Coolify because Coolify handles its own SSL
```

### Step 2.3 - Supabase Account and Project

Supabase has a Management API. Browser Use creates the account, then the CLI handles
project creation.

```bash
cat > /tmp/supabase_signup.md << 'EOF'
# Browser Use Task: Supabase Account

1. Navigate to https://supabase.com/dashboard/sign-in
2. Click "Continue with GitHub"
3. Authorize Supabase OAuth app
4. Complete organization setup: name it "crewcircle", type: personal
5. Navigate to Account > Access Tokens > Generate new token
6. Name: taxflow-automation, no expiry
7. COPY token: sbp_xxxxx
8. Note the Organization ID from the URL: https://supabase.com/dashboard/org/<ORG_ID>/settings
9. Output: SUPABASE_ACCESS_TOKEN=<sbp_xxxxx>, SUPABASE_ORG_ID=<org_id>
EOF
```

After Browser Use, create the project via Supabase Management API:
```bash
export SUPABASE_ACCESS_TOKEN="<from-browser-use>"
export SUPABASE_ORG_ID="<from-browser-use>"

# Generate a strong database password
DB_PASSWORD=$(python3 -c "import secrets,string; print(secrets.token_urlsafe(32))")
echo "Database password: $DB_PASSWORD"  # SAVE THIS

# Create Supabase project via Management API
PROJECT_RESPONSE=$(curl -s -X POST "https://api.supabase.com/v1/projects" \
  -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  --data "{
    \"name\": \"taxflow-prod\",
    \"organization_id\": \"$SUPABASE_ORG_ID\",
    \"plan\": \"free\",
    \"region\": \"ap-southeast-1\",
    \"db_pass\": \"$DB_PASSWORD\"
  }")

PROJECT_ID=$(echo $PROJECT_RESPONSE | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['id'])")
echo "Project ID: $PROJECT_ID"

# Poll until project status is ACTIVE_HEALTHY (takes 60-90 seconds)
echo "Waiting for Supabase project to become active..."
for i in $(seq 1 24); do
  STATUS=$(curl -s "https://api.supabase.com/v1/projects/$PROJECT_ID" \
    -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" | \
    python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','unknown'))")
  echo "Attempt $i/24: status=$STATUS"
  if [ "$STATUS" = "ACTIVE_HEALTHY" ]; then
    echo "PASS: Supabase project is ACTIVE_HEALTHY"
    break
  fi
  sleep 15
done

# Get API keys
KEYS=$(curl -s "https://api.supabase.com/v1/projects/$PROJECT_ID/api-keys" \
  -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN")

ANON_KEY=$(echo $KEYS | python3 -c "import json,sys; d=json.load(sys.stdin); print(next(k['api_key'] for k in d if k['name']=='anon'))")
SERVICE_KEY=$(echo $KEYS | python3 -c "import json,sys; d=json.load(sys.stdin); print(next(k['api_key'] for k in d if k['name']=='service_role'))")

SUPABASE_URL="https://$PROJECT_ID.supabase.co"

echo "SUPABASE_URL=$SUPABASE_URL"
echo "Project is live at: $SUPABASE_URL"

# Store all Supabase secrets in Doppler
doppler secrets set \
  SUPABASE_URL="$SUPABASE_URL" \
  SUPABASE_PROJECT_ID="$PROJECT_ID" \
  SUPABASE_ANON_KEY="$ANON_KEY" \
  SUPABASE_SERVICE_ROLE_KEY="$SERVICE_KEY" \
  SUPABASE_DB_PASSWORD="$DB_PASSWORD" \
  DATABASE_URL="postgresql://postgres:$DB_PASSWORD@db.$PROJECT_ID.supabase.co:5432/postgres" \
  SUPABASE_ACCESS_TOKEN="$SUPABASE_ACCESS_TOKEN" \
  --project taxflow --config prd

# Verification: connect to database and confirm it responds
doppler run --project taxflow --config prd -- \
  python3 -c "
import urllib.request, json, os
url = os.environ['SUPABASE_URL'] + '/rest/v1/'
req = urllib.request.Request(url, headers={
  'apikey': os.environ['SUPABASE_ANON_KEY'],
  'Authorization': 'Bearer ' + os.environ['SUPABASE_ANON_KEY']
})
resp = urllib.request.urlopen(req)
print('PASS: Supabase REST API responding, status:', resp.status)
"
```

### Step 2.4 - Run Database Migrations

Claude Code writes and runs all migrations. The schema covers all tables needed for
the entire 6-week build so the database does not need structural changes later.

```bash
cd ~/taxflow-ai

# Claude Code writes all migrations in one session.
# The AGENT.md for this task:
cat > apps/backend/AGENT.md << 'EOF'
# TaxFlow AI Backend - Claude Code Agent Instructions

## Your task now: Write database migrations 001 through 008

Create directory: apps/backend/supabase/migrations/

Write these files in order. Use PostgreSQL 16 syntax.
Run each migration after writing it to verify it applies.
The DATABASE_URL is available via: doppler run --project taxflow --config prd -- printenv DATABASE_URL

## Migration 001: clients.sql
Table: clients
- id uuid primary key default gen_random_uuid()
- business_name text not null
- business_type text not null check (business_type in ('dental','gp','specialist','pharmacy','physio','chiro','legal','accounting','financial_advice','property','construction','hospitality','retail','other'))
- email text unique not null
- abn text
- suburb text not null
- state text not null check (state in ('NSW','VIC','QLD','WA','SA','TAS','ACT','NT'))
- postcode text
- phone text
- firm_size_staff integer
- stripe_customer_id text unique
- stripe_subscription_id text unique
- subscription_status text not null default 'trialing' check (subscription_status in ('trialing','active','past_due','cancelled','paused'))
- tier text not null default 'professional' check (tier in ('starter','professional','practice','enterprise'))
- gbp_access_token text  -- encrypted at application layer
- gbp_refresh_token text -- encrypted at application layer
- gbp_location_id text
- voice_sample text  -- 3 sentences in firm's own words for Draft Agent
- firm_style jsonb default '{}'::jsonb  -- extracted by voice calibration service
- active_modules text[] default '{research}'::text[]
- do_not_contact boolean not null default false
- created_at timestamptz not null default now()
- updated_at timestamptz not null default now()
- deleted_at timestamptz  -- soft delete

## Migration 002: trial.sql
Table: trials
- id uuid primary key default gen_random_uuid()
- client_id uuid not null references clients(id) on delete cascade
- trial_started_at timestamptz not null default now()
- trial_ends_at timestamptz not null default (now() + interval '30 days')
- trial_status text not null default 'active' check (trial_status in ('active','converted','expired','cancelled'))
- card_collected_at timestamptz
- converted_at timestamptz
- queries_used integer not null default 0
- queries_cap integer not null default 100
- docs_used integer not null default 10
- docs_cap integer not null default 10

Postgres function: increment_trial_usage(p_client_id uuid, p_metric text)
  Atomically increments trials.queries_used or trials.docs_used for the client.
  Uses FOR UPDATE lock on the trial row to prevent race conditions.

## Migration 003: knowledge_chunks.sql
Table: knowledge_chunks
- id uuid primary key default gen_random_uuid()
- source_type text not null check (source_type in ('ato_ruling','ato_determination','ato_pbr','legislation','court_decision','ato_guide','ato_news'))
- source_url text not null
- source_title text not null
- citation text not null  -- e.g. "ITAA 1997 s.8-1" or "TR 2023/1" or "FCT v Cooling [1990]"
- content text not null
- embedding vector(1536)  -- pgvector, dimensionality matches text-embedding-3-small and claude
- chunk_index integer not null default 0  -- position within source document
- token_count integer
- last_scraped_at timestamptz not null default now()
- effective_date date  -- date ruling/legislation is effective
- is_current boolean not null default true

Index: CREATE INDEX ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
Index: CREATE INDEX ON knowledge_chunks (source_type, is_current);
Index: GIN index on content for full-text search: CREATE INDEX ON knowledge_chunks USING GIN(to_tsvector('english', content));

## Migration 004: queries.sql
Table: queries
- id uuid primary key default gen_random_uuid()
- client_id uuid not null references clients(id)
- user_email text not null
- question text not null
- module text not null check (module in ('research','ato_correspondence','document','regulatory_monitor'))
- status text not null default 'pending' check (status in ('pending','processing','completed','failed'))
- pipeline_outputs jsonb default '{}'::jsonb  -- stores each agent's output
- final_answer text
- citations jsonb default '[]'::jsonb  -- array of {citation, url, excerpt}
- confidence_score numeric(3,2)  -- 0.00 to 1.00
- model_used text  -- 'haiku' or 'sonnet'
- input_tokens integer
- output_tokens integer
- wall_time_ms integer
- error_message text
- created_at timestamptz not null default now()
- completed_at timestamptz

## Migration 005: documents.sql
Table: documents
- id uuid primary key default gen_random_uuid()
- client_id uuid not null references clients(id)
- query_id uuid references queries(id)
- document_type text not null check (document_type in ('advice_memo','ato_response','remission_request','objection_letter','private_ruling_application','engagement_letter','payg_variation','fbt_declaration'))
- title text not null
- content_md text not null  -- markdown source
- content_docx bytea  -- generated .docx file
- status text not null default 'draft' check (status in ('draft','approved','sent','archived'))
- approved_by text
- approved_at timestamptz
- created_at timestamptz not null default now()

## Migration 006: firm_knowledge.sql
Table: firm_knowledge
- id uuid primary key default gen_random_uuid()
- client_id uuid not null references clients(id) on delete cascade
- file_name text not null
- file_type text not null check (file_type in ('pdf','docx','txt'))
- content text not null
- embedding vector(1536)
- usage_count integer not null default 0
- created_at timestamptz not null default now()

Index: CREATE INDEX ON firm_knowledge USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);

## Migration 007: regulatory_alerts.sql
Table: regulatory_alerts
- id uuid primary key default gen_random_uuid()
- source text not null  -- 'ato','revenue_nsw','sro_vic','qro','fair_work','asic'
- alert_type text not null  -- 'new_ruling','rate_change','deadline','legislative_amendment'
- title text not null
- summary text
- effective_date date
- url text
- affected_client_types text[]  -- which client business types are affected
- draft_comms_md text  -- auto-drafted client communication
- processed boolean not null default false
- detected_at timestamptz not null default now()

## Migration 008: rls.sql
Enable Row Level Security on ALL tables.
Service role bypasses RLS (for backend API).
Anon role gets NO access to any table.
No user-level RLS policies needed because the backend API uses service role and
enforces client isolation in application code via the client_id foreign key.

Pattern for each table:
  ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
  CREATE POLICY "service_role_full_access" ON <table>
    USING (auth.role() = 'service_role');

Also enable pgvector extension:
  CREATE EXTENSION IF NOT EXISTS vector;
EOF

# Now run Claude Code to implement the migrations
# After Claude Code writes the files, run them:
doppler run --project taxflow --config prd -- \
  python3 << 'PYEOF'
import os
import psycopg2
from pathlib import Path

db_url = os.environ['DATABASE_URL']
migration_dir = Path('apps/backend/supabase/migrations')

conn = psycopg2.connect(db_url)
conn.autocommit = True
cur = conn.cursor()

migrations = sorted(migration_dir.glob('*.sql'))
for migration in migrations:
    print(f"Applying {migration.name}...")
    sql = migration.read_text()
    cur.execute(sql)
    print(f"  PASS: {migration.name}")

cur.close()
conn.close()
print("All migrations applied successfully")
PYEOF
```

Verification:
```bash
doppler run --project taxflow --config prd -- python3 << 'PYEOF'
import os, psycopg2

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()

expected_tables = ['clients','trials','knowledge_chunks','queries','documents','firm_knowledge','regulatory_alerts']
cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
existing = [row[0] for row in cur.fetchall()]

for table in expected_tables:
    status = 'PASS' if table in existing else 'FAIL'
    print(f'{status}: table {table}')

# Verify pgvector extension
cur.execute("SELECT extname FROM pg_extension WHERE extname='vector'")
print('PASS: pgvector extension' if cur.fetchone() else 'FAIL: pgvector extension')

# Verify RLS enabled
cur.execute("SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public'")
for row in cur.fetchall():
    print(f'  RLS {row[0]}: {\"enabled\" if row[1] else \"FAIL-DISABLED\"}')

cur.close()
conn.close()
PYEOF
```

### End of Day 2 Verification Checklist

```bash
# SSH to droplet works
ssh root@$DROPLET_IP "docker ps | grep coolify" && echo "PASS: Coolify running on droplet" || echo "FAIL: Coolify not running"

# Coolify web UI is up
curl -s -o /dev/null -w "%{http_code}" http://$DROPLET_IP:8000 | grep -q "200\|302" && echo "PASS: Coolify UI" || echo "FAIL: Coolify UI"

# DNS updated to real IP
dig A api.taxflow.crewcircle.com.au +short | grep -q "$DROPLET_IP" && echo "PASS: API DNS points to droplet" || echo "FAIL: DNS not updated yet"

# Supabase responding
doppler run --project taxflow --config prd -- python3 -c "
import urllib.request, os
url = os.environ['SUPABASE_URL'] + '/rest/v1/'
req = urllib.request.Request(url, headers={'apikey': os.environ['SUPABASE_ANON_KEY']})
resp = urllib.request.urlopen(req)
print('PASS: Supabase API' if resp.status == 200 else f'FAIL: Supabase status {resp.status}')
"

# All 7 tables exist
doppler run --project taxflow --config prd -- python3 -c "
import os, psycopg2
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute(\"SELECT COUNT(*) FROM pg_tables WHERE schemaname='public'\")
count = cur.fetchone()[0]
print(f'PASS: {count} tables in public schema' if count >= 7 else f'FAIL: only {count} tables')
"

# Doppler secrets count
doppler secrets --project taxflow --config prd --json | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(f'PASS: {len(d)} secrets in Doppler taxflow/prd')
"
```

---

## DAY 3: FastAPI Backend Scaffold

### Step 3.1 - Backend Application Structure

Claude Code writes the entire backend in one session. The pyproject.toml, config.py,
all routers, and the Dockerfile are all written by Claude Code from the AGENT.md spec.

```bash
cd ~/taxflow-ai/apps/backend

cat > AGENT.md << 'AGENTEOF'
# TaxFlow AI Backend - Full Scaffold

## Stack
- Python 3.12
- FastAPI with lifespan context manager (not @app.on_event deprecated pattern)
- uvicorn with uvloop
- supabase-py v2 (async client)
- pydantic-settings v2 for config
- APScheduler 3.x for background jobs
- python-multipart for file uploads
- anthropic SDK for LLM calls
- httpx for external HTTP calls
- python-docx for document generation
- weasyprint for PDF generation
- pgvector for vector operations

## Directory structure to create:
apps/backend/
  pyproject.toml
  Dockerfile
  .dockerignore
  src/
    taxflow/
      __init__.py
      main.py           -- FastAPI app, lifespan, router includes
      config.py         -- pydantic-settings, reads from env (Doppler injects)
      db.py             -- Supabase async client singleton
      scheduler.py      -- APScheduler setup, job registration
      middleware/
        __init__.py
        auth.py         -- JWT validation via Supabase Auth
        trial_gate.py   -- checks trial status, increments usage
        rate_limit.py   -- per-client rate limiting using sliding window in Supabase
      routers/
        __init__.py
        health.py       -- GET /health returns version, db status, scheduler status
        auth.py         -- POST /auth/signup, POST /auth/stripe-callback
        query.py        -- POST /query, GET /query/{id}, GET /query/stream/{id}
        documents.py    -- POST /documents/generate, GET /documents/{id}/download
        ato_response.py -- POST /ato-response/upload, GET /ato-response/{id}
        firm_knowledge.py -- POST /firm-knowledge/upload, DELETE /firm-knowledge/{id}
        webhooks.py     -- POST /webhooks/stripe (Stripe events)
      services/
        __init__.py
        llm_router.py   -- route to Haiku or Sonnet based on confidence threshold
        agents/
          __init__.py
          research.py   -- retrieval + generation + citation formatting
          draft.py      -- advice memo generation in firm's voice
          verify.py     -- cross-check draft against cited sources
          pipeline.py   -- orchestrates all 5 agents in sequence
        ato_correspondence/
          __init__.py
          classifier.py -- classify ATO letter type from PDF text
          handlers.py   -- per-letter-type response strategy
          drafter.py    -- produce ATO response draft
        knowledge/
          __init__.py
          retrieval.py  -- hybrid search: pgvector cosine + PostgreSQL full-text
          embedder.py   -- embed text chunks via Anthropic API (or a local model)
  tests/
    conftest.py         -- pytest fixtures, test database setup
    test_health.py
    test_auth.py
    test_query.py
    test_trial_gate.py

## config.py requirements
Use pydantic-settings BaseSettings. Every field reads from environment.
Field names must match Doppler secret names exactly (case-insensitive).
Required fields (no defaults, will fail fast if missing):
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_ANON_KEY,
  ANTHROPIC_API_KEY, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET,
  DATABASE_URL

Optional fields (have defaults):
  ENVIRONMENT: str = "production"
  APP_NAME: str = "taxflow"
  LOG_LEVEL: str = "INFO"
  ANTHROPIC_HAIKU_MODEL: str = "claude-haiku-4-5"
  ANTHROPIC_SONNET_MODEL: str = "claude-sonnet-4-6"
  HAIKU_CONFIDENCE_THRESHOLD: float = 0.72
  MAX_RETRIEVAL_CHUNKS: int = 10
  CHUNK_SIZE_TOKENS: int = 512
  CHUNK_OVERLAP_TOKENS: int = 64

## health.py requirements
GET /health must return within 200ms.
Response schema:
{
  "status": "ok",
  "version": "0.1.0",
  "environment": "production",
  "database": "connected" | "error: <message>",
  "scheduler": "running" | "stopped",
  "timestamp": "<ISO 8601>"
}
Test database with: SELECT 1 (timeout 2 seconds)

## trial_gate.py requirements
Middleware that runs before every /query and /documents endpoint.
1. Extract client_id from the authenticated JWT claims
2. Query trials table for the client's active trial
3. If subscription_status = 'active': allow through (paid subscriber)
4. If trial_status = 'expired' OR trial_ends_at < now(): return 402 with:
   {"error": "TRIAL_EXPIRED", "upgrade_url": "https://taxflow.crewcircle.com.au/upgrade"}
5. If queries_used >= queries_cap: return 402 with:
   {"error": "TRIAL_CAP_REACHED", "metric": "queries", "used": N, "cap": N}
6. On success: call increment_trial_usage(client_id, 'queries') Postgres function

## test_trial_gate.py requirements
Test 4 scenarios using pytest and httpx TestClient:
1. Active paid subscriber: 200 OK
2. Expired trial: 402 with TRIAL_EXPIRED code
3. Trial cap reached: 402 with TRIAL_CAP_REACHED code
4. Active trial within cap: 200 OK, trial.queries_used incremented by 1
Each test uses a fresh test database row created in conftest.py fixture.
AGENTEOF

# After Claude Code writes all files, install dependencies and run tests:
uv sync

# Run tests with Doppler secret injection
doppler run --project taxflow --config prd -- \
  uv run pytest tests/ -v --tb=short 2>&1 | tail -30
# Expected: 4 test files, all tests pass, no FAILED or ERROR lines
```

### Step 3.2 - Backend Dockerfile and Coolify Deploy

```bash
# Claude Code writes the Dockerfile as part of the scaffold.
# Expected content:
cat > apps/backend/Dockerfile << 'EOF'
FROM python:3.12-slim

WORKDIR /app

# Install system deps for psycopg2, weasyprint, python-docx
RUN apt-get update && apt-get install -y \
    gcc libpq-dev libpango-1.0-0 libpangoft2-1.0-0 \
    libharfbuzz0b libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv --no-cache-dir

# Copy dependency files first (Docker layer caching)
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --frozen

# Copy application code
COPY src/ ./src/

# Doppler injects all env vars at runtime - no .env file needed
EXPOSE 8000

CMD ["uv", "run", "uvicorn", "taxflow.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
EOF

cat > apps/backend/.dockerignore << 'EOF'
.venv/
__pycache__/
*.pyc
tests/
.pytest_cache/
*.env
.env*
EOF

# Build Docker image locally to verify it builds before deploying to Coolify
docker build -t taxflow-backend:test apps/backend/

# Verify image builds without error
docker images | grep taxflow-backend
# Expected: taxflow-backend test <recent timestamp>

# Test run the container with Doppler secrets
doppler run --project taxflow --config prd -- \
  docker run --rm \
  -e SUPABASE_URL \
  -e SUPABASE_SERVICE_ROLE_KEY \
  -e SUPABASE_ANON_KEY \
  -e ANTHROPIC_API_KEY \
  -e STRIPE_SECRET_KEY \
  -e STRIPE_WEBHOOK_SECRET \
  -e DATABASE_URL \
  -e ENVIRONMENT=production \
  -p 8001:8000 \
  taxflow-backend:test &

sleep 8

# Health check
curl -s http://localhost:8001/health | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['status'] == 'ok', f'Health check failed: {d}'
assert d['database'] == 'connected', f'DB not connected: {d}'
print('PASS: Backend health check')
print(f'  Database: {d[\"database\"]}')
print(f'  Scheduler: {d[\"scheduler\"]}')
"

# Stop local test container
docker stop $(docker ps -q --filter ancestor=taxflow-backend:test)
```

Deploy to Coolify (via Coolify API - after initial browser setup in Step 2.2):
```bash
# Coolify has an API. Get the API key from Coolify Settings > API.
# Browser Use gets this during Coolify setup or retrieve it now:
COOLIFY_API_KEY=$(ssh root@$DROPLET_IP "grep COOLIFY_API_KEY /data/coolify/.env 2>/dev/null | cut -d= -f2" || echo "GET FROM COOLIFY UI")

# Create application in Coolify via API
curl -s -X POST "http://$DROPLET_IP:8000/api/v1/applications" \
  -H "Authorization: Bearer $COOLIFY_API_KEY" \
  -H "Content-Type: application/json" \
  --data '{
    "name": "taxflow-backend",
    "git_repository": "https://github.com/<your-org>/taxflow-ai",
    "git_branch": "main",
    "build_pack": "dockerfile",
    "dockerfile_location": "apps/backend/Dockerfile",
    "port_exposes": "8000",
    "fqdn": "api.taxflow.crewcircle.com.au",
    "environment_variables": []
  }' | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(f'Application created: {d.get(\"uuid\",d)}')
"
# Note: actual Coolify API endpoints vary by version. If API fails, deploy via Coolify UI:
# New Application > GitHub > taxflow-ai repo > Dockerfile > port 8000 > domain api.taxflow.crewcircle.com.au
```

### End of Day 3 Verification

```bash
# Backend tests pass
doppler run --project taxflow --config prd -- \
  uv run pytest apps/backend/tests/ -v --tb=short | grep -E "PASSED|FAILED|ERROR" | head -20

# Docker image builds
docker images | grep taxflow-backend && echo "PASS: Docker image" || echo "FAIL: Docker image"

# Local health check passes
# (run local container as above and test /health)

# CI pipeline triggered and passing
gh run list --repo taxflow-ai --limit 1 | head -5
```

---

## DAY 4: Knowledge Base Ingestion Pipeline

### Step 4.1 - Scraper Architecture

The knowledge base scrapers run as daily APScheduler jobs. Each scraper:
1. Fetches documents from a public AU government source
2. Chunks each document into ~512-token segments with 64-token overlap
3. Generates embeddings via the Anthropic API (using claude's embedding capability)
   or via text-embedding-3-small from OpenAI (cheaper at $0.02/1M tokens vs Anthropic)
4. Stores chunks and embeddings in knowledge_chunks table

The embedding model choice: text-embedding-ada-002 (OpenAI, $0.10/1M tokens) or
text-embedding-3-small (OpenAI, $0.02/1M tokens). For 500,000 chunks at 512 tokens
average, that is 256M tokens = $5.12 total at text-embedding-3-small pricing.
This is a one-time cost for the initial load; daily deltas are small.

Alternative: use a local embedding model (all-MiniLM-L6-v2 via sentence-transformers,
free, 384 dimensions). Requires changing the vector column to vector(384).

Decision: use text-embedding-3-small (OpenAI). Small cost, high quality, no local GPU.

```bash
cat > packages/knowledge/AGENT.md << 'AGENTEOF'
# Knowledge Base Package - Claude Code Agent Instructions

## Your task: Build the complete knowledge ingestion pipeline

## Package structure:
packages/knowledge/
  pyproject.toml
  src/
    knowledge/
      __init__.py
      scraper_base.py    -- abstract base class for all scrapers
      scrapers/
        __init__.py
        ato_rulings.py   -- scrapes ATO Legal Database (Rulings, Determinations, PCGs)
        legislation.py   -- scrapes legislation.gov.au for key Acts
        austlii.py       -- scrapes AustLII for Federal Court + AAT decisions
      pipeline.py        -- orchestrates: scrape -> chunk -> embed -> upsert
      retrieval.py       -- hybrid search: pgvector cosine + PostgreSQL FTS
      embedder.py        -- wraps OpenAI text-embedding-3-small API

## scraper_base.py requirements
Abstract class ScraperBase with:
  @abstractmethod fetch_document_list() -> list[dict]
    Returns list of {url, title, citation, source_type, effective_date}
  @abstractmethod fetch_document_content(url: str) -> str
    Returns full text of one document
  
  Concrete method: run_delta() -> int
    1. Call fetch_document_list()
    2. For each document, check if knowledge_chunks has a row with source_url=url AND last_scraped_at > 24h ago
    3. If stale or missing: call fetch_document_content(url), run pipeline.process_document()
    4. Return count of documents processed

## ato_rulings.py requirements
Source: https://www.ato.gov.au/law/view/document
The ATO Legal Database has a sitemap at https://www.ato.gov.au/sitemap.xml
and specific indexes at:
  https://www.ato.gov.au/law/view/document?DocID=TXR/index  (Tax rulings index)
  https://www.ato.gov.au/law/view/document?DocID=TXD/index  (Tax determinations)
  https://www.ato.gov.au/law/view/document?DocID=PCG/index  (Practical compliance guidelines)

Use httpx with:
  - User-Agent: "TaxFlowAI/1.0 (research purposes; contact: crewcircle@zohomail.com.au)"
  - Rate limit: 1 request per 2 seconds (ATO servers are slow, be polite)
  - Retry: 3 attempts with exponential backoff on 429 or 5xx

Parse HTML with BeautifulSoup4. Extract:
  - title from <h1> or <title>
  - document citation from the ATO reference number in the URL or page
  - effective date from page content
  - body text: remove navigation, headers, footers, keep legislative content

## legislation.py requirements
Source: https://www.legislation.gov.au
Key legislation to scrape (these are the most-referenced in AU tax):
  - Income Tax Assessment Act 1997 (ITAA 1997): C2024C00329 or current compilation
  - Income Tax Assessment Act 1936 (ITAA 1936): C2024C00272
  - A New Tax System (Goods and Services Tax) Act 1999: C2023C00321
  - Fringe Benefits Tax Assessment Act 1986: C2015C00308
  - Superannuation Guarantee (Administration) Act 1992: C2023C00186
  - Fair Work Act 2009: C2024C00165
  - Corporations Act 2001: C2024C00065

API endpoint: https://api.legislation.gov.au/latest/details/<compilation_id>
HTML download: https://www.legislation.gov.au/Details/<compilation_id>/Download

Chunk at section level, not arbitrary token count.
Citation format: "ITAA 1997 s.8-1" for section 8-1 of ITAA 1997.

## austlii.py requirements  
Source: https://www.austlii.edu.au
Key databases:
  Full Federal Court: https://www.austlii.edu.au/cgi-bin/viewdb/au/cases/cth/FCA/
  Administrative Appeals Tribunal: https://www.austlii.edu.au/cgi-bin/viewdb/au/cases/cth/AATA/
  
Fetch the RSS feeds for recent decisions:
  https://www.austlii.edu.au/cgi-bin/rssdisp.cgi?db=/au/cases/cth/FCA&count=50
  https://www.austlii.edu.au/cgi-bin/rssdisp.cgi?db=/au/cases/cth/AATA&count=50

Citation format: "FCT v Smith [2023] FCA 1234"

## pipeline.py requirements
Function: process_document(text: str, metadata: dict) -> int
  Returns count of chunks upserted.

  1. Split text into chunks:
     - Target: 512 tokens (use tiktoken cl100k_base for token counting)
     - Overlap: 64 tokens
     - Split at sentence boundaries when possible (do not cut mid-sentence)
  
  2. For each chunk:
     - Call embedder.embed(chunk_text) -> list[float] of 1536 dimensions
     - Upsert to knowledge_chunks table:
       ON CONFLICT (source_url, chunk_index) DO UPDATE SET
         content = EXCLUDED.content,
         embedding = EXCLUDED.embedding,
         last_scraped_at = now()

## retrieval.py requirements
Function: hybrid_search(query: str, top_k: int = 10, source_types: list[str] = None) -> list[dict]

  1. Embed the query using embedder.embed(query)
  
  2. Run two searches in parallel (asyncio.gather):
     a. Semantic search:
        SELECT id, citation, content, source_url,
               1 - (embedding <=> $1::vector) AS cosine_sim
        FROM knowledge_chunks
        WHERE is_current = true
          AND ($2::text[] IS NULL OR source_type = ANY($2))
        ORDER BY embedding <=> $1::vector
        LIMIT 20
     
     b. Full-text search (BM25 approximation via PostgreSQL ts_rank):
        SELECT id, citation, content, source_url,
               ts_rank(to_tsvector('english', content), plainto_tsquery('english', $1)) AS text_rank
        FROM knowledge_chunks
        WHERE is_current = true
          AND to_tsvector('english', content) @@ plainto_tsquery('english', $1)
          AND ($2::text[] IS NULL OR source_type = ANY($2))
        ORDER BY text_rank DESC
        LIMIT 20
  
  3. Reciprocal Rank Fusion:
     For each document in either result set:
       rrf_score = 1/(60 + rank_semantic) + 1/(60 + rank_textual)
     Sort by rrf_score descending, return top_k
  
  Returns: list of {id, citation, content, source_url, score}

## embedder.py requirements
Uses OpenAI text-embedding-3-small (1536 dimensions).
OPENAI_API_KEY must be in environment (add to Doppler).

Function: embed(text: str) -> list[float]
  - Truncate text to 8192 tokens if needed (model limit)
  - Call OpenAI embeddings API
  - Return float list

Function: embed_batch(texts: list[str]) -> list[list[float]]
  - Batch up to 100 texts per API call
  - Handle rate limits with exponential backoff
AGENTEOF
```

Run initial knowledge base ingestion:
```bash
cd ~/taxflow-ai

# First add OpenAI API key to Doppler (needed for embeddings)
# Create OpenAI account and get API key, then:
doppler secrets set OPENAI_API_KEY="sk-..." --project taxflow --config prd

# Run the initial full scrape (this takes 2-4 hours for full corpus)
# Run in tmux or screen so it survives terminal disconnect
tmux new-session -d -s kb_ingestion '
  doppler run --project taxflow --config prd -- \
    uv run python3 -c "
import asyncio
from knowledge.scrapers.ato_rulings import ATORulingsScraper
from knowledge.scrapers.legislation import LegislationScraper
from knowledge.scrapers.austlii import AustLIIScraper

async def main():
    for scraper in [ATORulingsScraper(), LegislationScraper(), AustLIIScraper()]:
        print(f\"Starting {scraper.__class__.__name__}...\")
        count = await scraper.run_delta()
        print(f\"  Done: {count} documents processed\")

asyncio.run(main())
"
echo "Ingestion complete"
'
tmux attach -t kb_ingestion
# Ctrl+B D to detach and leave it running
```

Verification (run during or after ingestion):
```bash
doppler run --project taxflow --config prd -- python3 << 'PYEOF'
import os, psycopg2

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()

# Total chunks
cur.execute("SELECT COUNT(*) FROM knowledge_chunks")
total = cur.fetchone()[0]
print(f"Total chunks: {total}")

# By source type
cur.execute("SELECT source_type, COUNT(*) FROM knowledge_chunks GROUP BY source_type ORDER BY COUNT(*) DESC")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]} chunks")

# Verify embeddings are populated (non-null)
cur.execute("SELECT COUNT(*) FROM knowledge_chunks WHERE embedding IS NULL")
null_embeddings = cur.fetchone()[0]
print(f"PASS: 0 null embeddings" if null_embeddings == 0 else f"FAIL: {null_embeddings} null embeddings")

# Test a similarity search works
cur.execute("""
SELECT citation, content[:100]
FROM knowledge_chunks
ORDER BY embedding <=> (
    SELECT embedding FROM knowledge_chunks 
    WHERE content ILIKE '%capital gains tax%' LIMIT 1
) LIMIT 5
""")
print("\nSample similarity search results (top 5 for 'capital gains tax'):")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]}...")

cur.close()
conn.close()
PYEOF
```

Acceptance criteria for knowledge base:
- Minimum 5,000 chunks before Research Agent is usable
- Minimum 20,000 chunks for production accuracy targets
- 0 chunks with null embeddings
- Similarity search returns results in < 500ms

---

## DAY 5: Next.js Dashboard Scaffold

### Step 5.1 - Dashboard Application

```bash
cd ~/taxflow-ai/apps

# Create Next.js 15 app
npx create-next-app@latest dashboard \
  --typescript \
  --tailwind \
  --eslint \
  --app \
  --no-src-dir \
  --import-alias "@/*" \
  --yes

cd dashboard

# Install Supabase Auth and UI dependencies
pnpm add @supabase/supabase-js @supabase/ssr
pnpm add @radix-ui/react-dialog @radix-ui/react-dropdown-menu @radix-ui/react-label
pnpm add @radix-ui/react-toast lucide-react clsx tailwind-merge
pnpm add -D @types/node

# Create environment file for local development
cat > .env.local << 'EOF'
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
NEXT_PUBLIC_API_URL=http://localhost:8000
EOF

# Populate from Doppler for local dev
doppler run --project taxflow --config prd -- bash -c '
echo "NEXT_PUBLIC_SUPABASE_URL=$SUPABASE_URL" >> .env.local
echo "NEXT_PUBLIC_SUPABASE_ANON_KEY=$SUPABASE_ANON_KEY" >> .env.local
'

# Claude Code writes the dashboard scaffold from this AGENT.md
cat > AGENT.md << 'AGENTEOF'
# TaxFlow Dashboard - Next.js 15 App Router Scaffold

## Write these files:

### app/layout.tsx
Root layout with: Supabase Auth provider, Toaster component, Inter font

### app/page.tsx  
Redirects to /dashboard if authenticated, else to /login

### app/login/page.tsx
Magic link sign-in form (email only, no password).
Calls supabase.auth.signInWithOtp({ email, options: { emailRedirectTo: 'https://taxflow.crewcircle.com.au/auth/callback' } })
Shows: "Check your email for a sign-in link"

### app/auth/callback/route.ts
Handles the magic link callback: exchanges code for session, redirects to /dashboard

### app/dashboard/layout.tsx
Sidebar navigation with links to:
  /dashboard (overview)
  /dashboard/query (ask a question)
  /dashboard/ato-response (ATO correspondence)
  /dashboard/documents (document library)
  /dashboard/knowledge (firm knowledge)
  /dashboard/settings (firm settings)
Shows trial banner at top.

### app/dashboard/page.tsx
Overview: shows today's query count, docs produced this week, trial days remaining.
Uses realistic AU stub data with DEMO badges on all metrics (not connected to real data yet).
Include a "Quick question" shortcut that links to /dashboard/query

### app/dashboard/query/page.tsx
Query interface:
  - Large textarea for question input
  - Submit button
  - Shows streaming response below
  - Citations rendered as numbered footnotes with clickable links
  - Copy to clipboard button on response
  - "Save as document" button (stub with DEMO badge for now)

### components/TrialBanner.tsx
Trial status banner shown at top of all dashboard pages.
4 states:
  active: "Trial: {N} days remaining"  (green, dismissible)
  expiring_soon: "Trial ends in {N} days - add payment to keep access" (amber, persistent)
  card_required: "Trial ends tomorrow - add card now" (red, persistent, CTA button)
  expired: "Your trial has ended - upgrade to continue" (red, full-width, CTA button, all features locked)
For now, use trial_status='active', days_remaining=28 as hardcoded stub.
Replace with real API call in Week 4.

### app/api/query/route.ts
API route (Next.js route handler) that proxies to the FastAPI backend.
POST /api/query -> POST $NEXT_PUBLIC_API_URL/query
Adds Authorization header from Supabase session.
Returns streaming response via ReadableStream.

## TypeScript requirements
Use strict mode. All components must be typed.
No 'any' types. Use 'unknown' if type is not known.
All async functions must handle errors with try/catch.
AGENTEOF

# After Claude Code writes the files:
pnpm dev &
sleep 5
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000
# Expected: 200

# Typecheck
pnpm typecheck
# Expected: no TypeScript errors

# Stop dev server
kill %1
```

### Step 5.2 - Deploy Dashboard to Vercel

```bash
# Install Vercel CLI
pnpm add -g vercel

# Link to Vercel (first time - creates project)
cd ~/taxflow-ai/apps/dashboard
vercel --yes
# Prompts: Set up and deploy? Y, Which scope? (your account), Link to existing project? N
# Project name: taxflow-dashboard
# Directory: ./  (already in apps/dashboard)

# Set environment variables in Vercel (from Doppler)
doppler run --project taxflow --config prd -- bash -c '
vercel env add NEXT_PUBLIC_SUPABASE_URL production <<< "$SUPABASE_URL"
vercel env add NEXT_PUBLIC_SUPABASE_ANON_KEY production <<< "$SUPABASE_ANON_KEY"
vercel env add NEXT_PUBLIC_API_URL production <<< "https://api.taxflow.crewcircle.com.au"
'

# Deploy to production
vercel --prod

# Get the deployment URL
VERCEL_URL=$(vercel inspect --json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('url',''))" 2>/dev/null || echo "check vercel dashboard")
echo "Dashboard deployed to: https://$VERCEL_URL"

# Add custom domain in Vercel
vercel domains add taxflow.crewcircle.com.au
# Vercel will provide DNS instructions - but CNAME to cname.vercel-dns.com is already set in Cloudflare (Step 1.3)

# Verify
curl -s -o /dev/null -w "%{http_code}" https://taxflow.crewcircle.com.au
# Expected: 200 or 307 (redirect to /login)
```

---

## DAYS 6-7: Integration Testing and Advisory Board Outreach

### Day 6 - End-to-End Test and GitHub Actions Fix

```bash
# Run full test suite
cd ~/taxflow-ai

# Backend tests
doppler run --project taxflow --config prd -- \
  uv run pytest apps/backend/tests/ -v 2>&1 | tail -20

# Dashboard typecheck
cd apps/dashboard && pnpm typecheck && pnpm lint && cd ../..

# End-to-end smoke test
doppler run --project taxflow --config prd -- python3 << 'PYEOF'
import httpx, time

BASE = "https://api.taxflow.crewcircle.com.au"

# 1. Health check
r = httpx.get(f"{BASE}/health", timeout=10)
assert r.status_code == 200, f"Health failed: {r.status_code}"
d = r.json()
assert d["status"] == "ok", f"Status not ok: {d}"
assert d["database"] == "connected", f"DB not connected: {d}"
print("PASS: /health")

print("All smoke tests passed")
PYEOF

# Fix any CI failures
gh run list --limit 3
# If any failed: gh run view <run-id> --log-failed
```

### Day 7 - Advisory Board Outreach (3 LinkedIn Messages)

```bash
# Claude drafts 3 personalised LinkedIn messages for managing partners at AU accounting firms.
# The founder reviews and sends manually via LinkedIn.

cat > /tmp/advisory_board_outreach.md << 'EOF'
# Claude Task: Draft 3 Advisory Board Outreach Messages

Context:
- Product: TaxFlow AI (AI workflow platform for AU accounting firms)
- Stage: Pre-launch, looking for 2 practising CAs or CPAs and 1 AU tax lawyer
- Offer: 0.25% equity as advisor, monthly 30-min feedback session, named credit on platform
- Product benefit: turns 2-hour tax research into 3-minute AI workflow with AU citations

Write 3 personalised LinkedIn messages (max 300 characters each - LinkedIn limit):
1. For a CPA managing partner at a 10-person Sydney firm that does tax and compliance
2. For a CA managing partner at a Melbourne practice focusing on SME advisory
3. For a tax barrister or specialist tax lawyer in Sydney or Melbourne

Each message must:
- Reference something specific about their professional background (not generic)
- Be direct about what is being asked (advisory role, time commitment, equity offer)
- Not sound like a mass-message template
- End with a question to prompt a reply

Output format: numbered list, one message per item
EOF

# Founder reviews output and sends manually via LinkedIn
# Target: 3 messages sent by end of Day 7
```

### Week 1 Final Verification (all must pass before Week 2 begins)

```bash
cat << 'VERIFY'
=== WEEK 1 COMPLETION CHECK ===
Run all commands below. All must show PASS.
VERIFY

# 1. Cloudflare zone active
curl -s "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
  print('PASS: CF zone active' if d['result']['status']=='active' else 'FAIL: CF zone not active')"

# 2. Subdomain DNS resolves
dig A api.taxflow.crewcircle.com.au +short | grep -q "." && \
  echo "PASS: api.taxflow DNS resolves" || echo "FAIL: api.taxflow DNS"

# 3. Backend health check
curl -sf https://api.taxflow.crewcircle.com.au/health | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
  print('PASS: Backend live' if d['status']=='ok' else f'FAIL: {d}')"

# 4. Dashboard loads
curl -sf https://taxflow.crewcircle.com.au | grep -q "TaxFlow\|taxflow" && \
  echo "PASS: Dashboard live" || echo "FAIL: Dashboard not loading"

# 5. Supabase: all tables exist
doppler run --project taxflow --config prd -- python3 -c "
import os, psycopg2
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute(\"SELECT COUNT(*) FROM pg_tables WHERE schemaname='public'\")
count = cur.fetchone()[0]
print(f'PASS: {count}/7 tables' if count >= 7 else f'FAIL: only {count} tables')
"

# 6. Knowledge base has chunks
doppler run --project taxflow --config prd -- python3 -c "
import os, psycopg2
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM knowledge_chunks')
count = cur.fetchone()[0]
print(f'PASS: {count} knowledge chunks' if count >= 5000 else f'FAIL: only {count} chunks (need 5000+)')
"

# 7. Doppler secrets
doppler secrets --project taxflow --config prd --json | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
  print(f'PASS: {len(d)} secrets in Doppler' if len(d) >= 15 else f'FAIL: only {len(d)} secrets')"

# 8. CI pipeline green
gh run list --repo taxflow-ai --limit 1 --json conclusion | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
  print('PASS: CI green' if d and d[0]['conclusion']=='success' else f'FAIL: CI not green - {d}')"

# 9. GitHub repo private
gh repo view taxflow-ai --json visibility | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
  print('PASS: Repo private' if d['visibility']=='PRIVATE' else 'FAIL: Repo not private')"

# 10. Advisory board outreach
echo "MANUAL CHECK: 3 LinkedIn messages sent? (Y/N)"
```
