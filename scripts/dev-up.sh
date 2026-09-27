#!/usr/bin/env bash
# Bring up the local stack (Postgres 17 + Wrappers, PostgREST, Kong) and the fixture mock.
# The full `supabase start` (studio, analytics, realtime, storage, ...) is not needed and times out
# on health checks on smaller machines; analytics is also disabled in supabase/config.toml.
#   scripts/dev-up.sh            # trimmed stack + mock on :8787
#   scripts/dev-up.sh --no-mock  # stack only (use with a real key: SERPAPI_API_URL unset)
set -euo pipefail
cd "$(dirname "$0")/.."

supabase start \
  -x gotrue,realtime,storage-api,imgproxy,mailpit,postgres-meta,studio,edge-runtime,logflare,vector,supavisor \
  --ignore-health-check 2>&1 | grep -E "DB_URL|API_URL|error" || true

for _ in $(seq 1 30); do
  docker inspect -f '{{.State.Health.Status}}' "$(docker ps --filter 'name=supabase_db_' --format '{{.Names}}' | head -1)" 2>/dev/null | grep -q healthy && break
  sleep 2
done

if [[ "${1:-}" != "--no-mock" ]]; then
  pkill -f "mock/server.py" 2>/dev/null || true
  nohup python3 mock/server.py --port 8787 --fixtures fixtures/serp > /tmp/serpapi-mock.log 2>&1 &
  sleep 1
  curl -sf -m 5 "http://127.0.0.1:8787/account.json?api_key=x" >/dev/null && echo "mock serpapi on :8787 (log: /tmp/serpapi-mock.log)"
  echo "next: SERPAPI_API_URL=http://host.docker.internal:8787 SERPAPI_API_KEY=mock-key scripts/load-local.sh && scripts/apply-sql.sh"
else
  echo "next: scripts/load-local.sh && scripts/apply-sql.sh   (key from ~/.serpapi_key)"
fi
