#!/usr/bin/env bash
# Remaining infra steps that require interactive permission:
#  1. Create the two Cloudflare DNS records (idempotent - reports exists if already created)
#  2. Attach the dashboard domain to the Vercel project
# Backend deployment is separate: scripts/deploy_backend.sh (Docker Compose + Caddy).
#
# Run:  doppler run --project taxflow --config prd -- bash scripts/finish_infra.sh

set -euo pipefail

DROPLET_IP="${DROPLET_IP:-170.64.183.45}"

if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
  echo "CLOUDFLARE_API_TOKEN not set. Run via:"
  echo "  doppler run --project taxflow --config prd -- bash scripts/finish_infra.sh"
  exit 1
fi

echo "=== 1/2 Creating DNS records ==="
curl -s -X POST "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json" \
  --data '{"type":"CNAME","name":"taxflow","content":"cname.vercel-dns.com","proxied":false}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('PASS: taxflow CNAME' if d['success'] else f'exists/FAIL: {d[\"errors\"]}')"

curl -s -X POST "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json" \
  --data "{\"type\":\"A\",\"name\":\"api.taxflow\",\"content\":\"$DROPLET_IP\",\"proxied\":false,\"comment\":\"TaxFlow backend droplet\"}" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('PASS: api.taxflow A record' if d['success'] else f'exists/FAIL: {d[\"errors\"]}')"

echo "=== 2/2 Attaching dashboard domain to Vercel ==="
# CLI v50 syntax: single argument, applies to the project linked in this directory
(cd "$(dirname "$0")/../apps/dashboard" && vercel domains add taxflow.crewcircle.com.au || true)

echo "=== Verification ==="
echo -n "api.taxflow DNS: " && dig +short A api.taxflow.crewcircle.com.au
echo -n "taxflow DNS:     " && dig +short CNAME taxflow.crewcircle.com.au
echo -n "dashboard:       " && curl -s -o /dev/null -w "%{http_code}\n" --max-time 15 https://taxflow.crewcircle.com.au || true
echo
echo "Next: deploy the backend with:"
echo "  doppler run --project taxflow --config prd -- bash scripts/deploy_backend.sh"
