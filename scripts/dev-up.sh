#!/usr/bin/env bash
# Bring up the local stack (Postgres 17 + Wrappers, PostgREST, Kong, Auth) and the fixture mock.
# The full `supabase start` (studio, analytics, realtime, storage, ...) is not needed and times out
# on health checks on smaller machines; analytics is also disabled in supabase/config.toml.
# Auth (gotrue) stays on so the playground can sign in; scripts/demo-user.sh creates its demo user.
#   scripts/dev-up.sh            # trimmed stack + auth + mock on :8787 + demo user
#   scripts/dev-up.sh --no-mock  # stack only (use with a real key: SERPAPI_API_URL unset)
#   scripts/dev-up.sh --no-auth  # also skip gotrue (smallest footprint; playground stays anon-only)
# Linux: the supabase CLI adds host.docker.internal:host-gateway to its containers, so the db container
# reaches the mock (which listens on 0.0.0.0:8787) at http://host.docker.internal:8787 there too.
set -euo pipefail
cd "$(dirname "$0")/.."

MOCK=1 AUTH=1
for a in "$@"; do
  case "$a" in
    --no-mock) MOCK=0 ;;
    --no-auth) AUTH=0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

missing=0
need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1 ($2)" >&2; missing=1; }; }
need docker   "https://docs.docker.com/get-docker/"
need supabase "https://supabase.com/docs/guides/local-development/cli/getting-started"
need psql     "PostgreSQL client, e.g. brew install libpq / apt install postgresql-client"
need python3  "Python 3, for the mock and scripts/gen.py"
need curl     "curl"
if command -v docker >/dev/null 2>&1 && ! docker info >/dev/null 2>&1; then
  echo "docker is not running (start Docker Desktop / dockerd)" >&2; missing=1
fi
[[ $missing -eq 0 ]] || exit 1

EXCLUDE=realtime,storage-api,imgproxy,mailpit,postgres-meta,studio,edge-runtime,logflare,vector,supavisor
[[ $AUTH -eq 1 ]] || EXCLUDE="gotrue,$EXCLUDE"

# Print only the URLs (the CLI's status output also lists the local demo keys and JWT secret).
supabase start -x "$EXCLUDE" --ignore-health-check 2>&1 | grep -iE "^[[:space:]]*error" || true
supabase status -o env 2>/dev/null | grep -E '^(API_URL|DB_URL)=' || true

for _ in $(seq 1 30); do
  docker inspect -f '{{.State.Health.Status}}' "$(docker ps --filter 'name=supabase_db_' --format '{{.Names}}' | head -1)" 2>/dev/null | grep -q healthy && break
  sleep 2
done

if [[ $AUTH -eq 1 ]]; then
  scripts/demo-user.sh || echo "demo user not created yet; rerun scripts/demo-user.sh once auth is up" >&2
fi

if [[ $MOCK -eq 1 ]]; then
  pkill -f "mock/server.py" 2>/dev/null || true
  nohup python3 mock/server.py --port 8787 --fixtures fixtures/serp > /tmp/serpapi-mock.log 2>&1 &
  sleep 1
  curl -sf -m 5 "http://127.0.0.1:8787/account.json?api_key=x" >/dev/null && echo "mock serpapi on :8787 (log: /tmp/serpapi-mock.log)"
  echo "next: SERPAPI_API_URL=http://host.docker.internal:8787 SERPAPI_API_KEY=mock-key scripts/load-local.sh && scripts/apply-sql.sh && scripts/smoke-assert.sh"
else
  echo "next: scripts/load-local.sh && scripts/apply-sql.sh   (key from ~/.serpapi_key)"
fi
