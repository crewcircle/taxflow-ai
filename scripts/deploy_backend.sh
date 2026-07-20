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

# sha-tagged images (Decision #2487): tag each build taxflow-backend:<git-sha> so a
# failed smoke test can re-up the previously-running tag. GITHUB_SHA is set in CI;
# fall back to `git rev-parse` for local/manual runs.
BACKEND_IMAGE_TAG="${BACKEND_IMAGE_TAG:-${GITHUB_SHA:-}}"
if [ -z "$BACKEND_IMAGE_TAG" ]; then
  BACKEND_IMAGE_TAG="$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo "latest")"
fi
# How many old sha-tagged images to retain on the droplet (newest kept + this many prior).
KEEP_TAGS="${KEEP_TAGS:-3}"

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
LLM_API_BASE=${LLM_API_BASE:-}
LLM_API_KEY=${LLM_API_KEY:-}
OPENCODE_API_KEY=${OPENCODE_API_KEY:-}
ENVIRONMENT=production
ENVEOF

echo "=== 3/4 Syncing code ==="
rsync -az --delete \
  --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude 'tests' --exclude '.env' \
  "$REPO_ROOT/apps/backend/" "root@$DROPLET_IP:/opt/taxflow/backend/"
rsync -az "$REPO_ROOT/deploy/" "root@$DROPLET_IP:/opt/taxflow/deploy/"

echo "=== 4/4 Building, deploying, and smoke-testing (tag: $BACKEND_IMAGE_TAG) ==="
# Everything below runs on the droplet. The smoke test is the deploy gate: a failed
# health check re-ups the previously-running sha-tagged image and exits non-zero, so
# CI's deploy-backend job goes red. Positional args pass the new tag + retention count
# into the quoted heredoc (no local expansion).
ssh "root@$DROPLET_IP" bash -s -- "$BACKEND_IMAGE_TAG" "$KEEP_TAGS" << 'REMOTE'
set -euo pipefail

NEW_TAG="$1"
KEEP_TAGS="$2"
COMPOSE_FILE="docker-compose.deployed.yml"
MARKER_FILE="/opt/taxflow/backend_current_tag"

cd /opt/taxflow/deploy
# compose context expects ../apps/backend relative to deploy/; point it at the synced path.
# Rollback re-ups against this SAME deployed file, so it is regenerated every deploy.
sed 's|context: ../apps/backend|context: ../backend|' docker-compose.yml > "$COMPOSE_FILE"

# Record the currently-running tag BEFORE we touch anything, so we can roll back to it.
# Prefer the persisted marker (survives container recreation); fall back to the running
# container's image tag; empty means this is the first deploy.
PREV_TAG=""
if [ -f "$MARKER_FILE" ]; then
  PREV_TAG="$(cat "$MARKER_FILE")"
else
  PREV_TAG="$(docker inspect --format '{{ index .Config.Image }}' \
    "$(docker compose -f "$COMPOSE_FILE" ps -q backend 2>/dev/null || true)" 2>/dev/null \
    | sed 's/^taxflow-backend://' || true)"
fi
echo "Previous tag: ${PREV_TAG:-<none, first deploy>}"
echo "New tag:      $NEW_TAG"

# --- health probe -----------------------------------------------------------
# The backend port (8000) is only `expose`d, not host-published, and curl is not
# guaranteed inside the image, so probe via the container's Python urllib (same
# pattern as the compose healthcheck). Returns 0 iff status==ok AND database==connected.
health_ok() {
  docker compose -f "$COMPOSE_FILE" exec -T backend python3 -c '
import json, sys, urllib.request
try:
    body = urllib.request.urlopen("http://localhost:8000/health", timeout=5).read()
    data = json.loads(body)
except Exception as e:  # noqa: BLE001
    print("health probe error: %s" % e, file=sys.stderr)
    sys.exit(1)
ok = data.get("status") == "ok" and data.get("database") == "connected"
print("status=%s database=%s" % (data.get("status"), data.get("database")))
sys.exit(0 if ok else 1)
'
}

# Bounded retry + total timeout: 20 attempts x 5s = ~100s max.
smoke_test() {
  local attempts=20 delay=5 i
  for ((i = 1; i <= attempts; i++)); do
    if health_ok; then
      echo "Smoke test passed on attempt $i/$attempts."
      return 0
    fi
    echo "Smoke test attempt $i/$attempts not healthy yet; retrying in ${delay}s..."
    sleep "$delay"
  done
  return 1
}

# --- build + deploy new tag -------------------------------------------------
BACKEND_IMAGE_TAG="$NEW_TAG" docker compose -f "$COMPOSE_FILE" build backend
BACKEND_IMAGE_TAG="$NEW_TAG" docker compose -f "$COMPOSE_FILE" up -d backend caddy
docker compose -f "$COMPOSE_FILE" ps

# --- gate: smoke test, roll back on failure ---------------------------------
if smoke_test; then
  echo "$NEW_TAG" > "$MARKER_FILE"
  echo "Deploy of $NEW_TAG healthy."
  # Prune old sha-tagged images, keeping the newest $KEEP_TAGS.
  mapfile -t OLD_TAGS < <(docker images 'taxflow-backend' \
    --format '{{.Tag}}' | grep -v '^latest$' | tail -n +"$((KEEP_TAGS + 1))" || true)
  for t in "${OLD_TAGS[@]:-}"; do
    [ -z "$t" ] && continue
    [ "$t" = "$NEW_TAG" ] && continue
    echo "Pruning old image taxflow-backend:$t"
    docker image rm "taxflow-backend:$t" 2>/dev/null || true
  done
else
  echo "SMOKE TEST FAILED for $NEW_TAG." >&2
  if [ -n "$PREV_TAG" ] && [ "$PREV_TAG" != "$NEW_TAG" ]; then
    echo "Rolling back to previous tag: $PREV_TAG (re-up, no rebuild)..." >&2
    BACKEND_IMAGE_TAG="$PREV_TAG" docker compose -f "$COMPOSE_FILE" up -d --no-build backend
    if smoke_test; then
      echo "Rollback to $PREV_TAG is healthy; keeping previous version." >&2
      echo "$PREV_TAG" > "$MARKER_FILE"
    else
      echo "ROLLBACK health check ALSO FAILED - backend may be down." >&2
    fi
  else
    echo "First deploy (no previous tag) - no restore possible; failing loudly." >&2
  fi
  exit 1
fi
REMOTE

echo "=== Verification ==="
sleep 5
echo -n "https://api.taxflow.crewcircle.com.au/health -> "
curl -s --max-time 20 https://api.taxflow.crewcircle.com.au/health || echo "(cert may take ~60s on first run - retry shortly)"
echo
