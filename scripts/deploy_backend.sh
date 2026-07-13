#!/usr/bin/env bash
# Deploy the TaxFlow backend to the droplet with Docker Compose + Caddy.
# Idempotent: first run installs Docker and swap; later runs just redeploy.
#
# Run from the repo root, with secrets injected by Doppler:
#   doppler run --project taxflow --config prd -- bash scripts/deploy_backend.sh
#
# Requires: SSH key access to root@$DROPLET_IP (the key registered at droplet creation).

set -euo pipefail

DROPLET_IP="${DROPLET_IP:-170.64.183.45}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

REQUIRED_VARS=(SUPABASE_URL SUPABASE_SERVICE_ROLE_KEY SUPABASE_ANON_KEY ANTHROPIC_API_KEY
               OPENAI_API_KEY STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET DATABASE_URL
               STRIPE_STARTER_PRICE_ID STRIPE_PROFESSIONAL_PRICE_ID)
for var in "${REQUIRED_VARS[@]}"; do
  if [ -z "${!var:-}" ]; then
    echo "Missing $var - run via: doppler run --project taxflow --config prd -- bash scripts/deploy_backend.sh"
    exit 1
  fi
done

echo "=== 1/4 First-run server setup (Docker, swap, firewall) ==="
ssh -o StrictHostKeyChecking=accept-new "root@$DROPLET_IP" bash -s << 'REMOTE'
set -e
if ! command -v docker >/dev/null; then
  apt-get update -qq
  curl -fsSL https://get.docker.com | sh
fi
# Remove any leftovers from the abandoned Coolify install attempt
if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q coolify; then
  docker ps -a --format '{{.Names}}' | grep coolify | xargs -r docker rm -f
  rm -rf /data/coolify
  docker system prune -af --volumes >/dev/null
  echo "removed Coolify leftovers"
fi
# 1GB swap protects Docker builds on the 1GB droplet
if ! swapon --show | grep -q swapfile; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
# Basic firewall: SSH + HTTP/HTTPS only
if command -v ufw >/dev/null; then
  ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
  ufw --force enable >/dev/null
fi
mkdir -p /opt/taxflow
echo "server ready"
REMOTE

echo "=== 2/4 Writing production env file ==="
ssh "root@$DROPLET_IP" "cat > /opt/taxflow/.env && chmod 600 /opt/taxflow/.env" << ENVEOF
SUPABASE_URL=$SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY=$SUPABASE_SERVICE_ROLE_KEY
SUPABASE_ANON_KEY=$SUPABASE_ANON_KEY
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
OPENAI_API_KEY=$OPENAI_API_KEY
STRIPE_SECRET_KEY=$STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET=$STRIPE_WEBHOOK_SECRET
STRIPE_STARTER_PRICE_ID=$STRIPE_STARTER_PRICE_ID
STRIPE_PROFESSIONAL_PRICE_ID=$STRIPE_PROFESSIONAL_PRICE_ID
DATABASE_URL=$DATABASE_URL
R2_ACCOUNT_ID=${R2_ACCOUNT_ID:-}
R2_ACCESS_KEY_ID=${R2_ACCESS_KEY_ID:-}
R2_SECRET_ACCESS_KEY=${R2_SECRET_ACCESS_KEY:-}
R2_BUCKET_NAME=${R2_BUCKET_NAME:-}
ENVIRONMENT=production
ENVEOF

echo "=== 3/4 Syncing code ==="
rsync -az --delete \
  --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude 'tests' --exclude '.env' \
  "$REPO_ROOT/apps/backend/" "root@$DROPLET_IP:/opt/taxflow/backend/"
rsync -az "$REPO_ROOT/deploy/" "root@$DROPLET_IP:/opt/taxflow/deploy/"

echo "=== 4/4 Building and starting containers ==="
ssh "root@$DROPLET_IP" bash -s << 'REMOTE'
set -e
cd /opt/taxflow/deploy
# compose context expects ../apps/backend relative to deploy/; point it at the synced path
sed 's|context: ../apps/backend|context: ../backend|' docker-compose.yml > docker-compose.deployed.yml
docker compose -f docker-compose.deployed.yml up -d --build
sleep 10
docker compose -f docker-compose.deployed.yml ps
REMOTE

echo "=== Verification ==="
sleep 5
echo -n "https://api.taxflow.crewcircle.com.au/health -> "
curl -s --max-time 20 https://api.taxflow.crewcircle.com.au/health || echo "(cert may take ~60s on first run - retry shortly)"
echo
