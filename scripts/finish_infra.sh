#!/usr/bin/env bash
# Remaining infra steps that require interactive permission:
#  1. Create the two Cloudflare DNS records
#  2. Install Coolify on the DigitalOcean droplet
# Run:  bash scripts/finish_infra.sh
# Requires: CLOUDFLARE_API_TOKEN and CLOUDFLARE_ZONE_ID in env, or Doppler CLI configured.

set -euo pipefail

DROPLET_IP="170.64.183.45"

if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
  echo "CLOUDFLARE_API_TOKEN not set. Export it or run via:"
  echo "  doppler run --project taxflow --config prd -- bash scripts/finish_infra.sh"
  exit 1
fi

echo "=== 1/3 Creating DNS records ==="
curl -s -X POST "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json" \
  --data '{"type":"CNAME","name":"taxflow","content":"cname.vercel-dns.com","proxied":false}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('PASS: taxflow CNAME' if d['success'] else f'FAIL/exists: {d[\"errors\"]}')"

curl -s -X POST "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json" \
  --data "{\"type\":\"A\",\"name\":\"api.taxflow\",\"content\":\"$DROPLET_IP\",\"proxied\":false,\"comment\":\"TaxFlow backend droplet\"}" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('PASS: api.taxflow A record' if d['success'] else f'FAIL/exists: {d[\"errors\"]}')"

echo "=== 2/3 Installing Coolify on droplet (takes ~5-10 min) ==="
ssh -o StrictHostKeyChecking=accept-new "root@$DROPLET_IP" bash -s << 'REMOTE'
set -e
if docker ps 2>/dev/null | grep -q coolify; then
  echo "Coolify already running - skipping install"
else
  apt-get update -qq
  curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash
  sleep 20
fi
docker ps | grep coolify | head -5 && echo "PASS: Coolify running"
REMOTE

echo "=== 2.5/3 Attaching dashboard domain to Vercel ==="
# Project is already linked (apps/dashboard/.vercel) and the production deployment
# is Ready; attaching the domain makes it publicly reachable.
(cd "$(dirname "$0")/../apps/dashboard" && vercel domains add taxflow.crewcircle.com.au taxflow-dashboard || true)

echo "=== 3/3 Verification ==="
echo -n "Coolify UI http status: "
curl -s -o /dev/null -w "%{http_code}\n" "http://$DROPLET_IP:8000" || true
echo -n "api.taxflow DNS: "
dig +short A api.taxflow.crewcircle.com.au || true
echo
echo "Next: open http://$DROPLET_IP:8000 in a browser, create the Coolify admin"
echo "account (crewcircle@zohomail.com.au), connect the GitHub repo, and add the"
echo "backend app (Dockerfile at apps/backend/Dockerfile, port 8000,"
echo "domain api.taxflow.crewcircle.com.au)."
