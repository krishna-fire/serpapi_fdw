#!/usr/bin/env bash
# Plain Postgres (no Supabase): a stock postgres:17 (Debian trixie) container with the `wrappers` extension
# installed from Supabase's .deb release. Then use the normal scripts with DB_URL/CONTAINER set:
#
#   scripts/plain-pg-up.sh
#   export DB_URL=postgresql://postgres:postgres@127.0.0.1:55432/postgres CONTAINER=serpapi-plainpg
#   SERPAPI_API_URL=http://host.docker.internal:8787 SERPAPI_API_KEY=mock-key scripts/load-local.sh   # or a real key
#   scripts/apply-sql.sh && psql "$DB_URL" -f scripts/smoke.sql
set -euo pipefail

NAME="${NAME:-serpapi-plainpg}"
PORT="${PORT:-55432}"
PG="${PG:-17}"
WRAPPERS="${WRAPPERS:-0.6.3}"
# The wrappers .deb links against a recent libstdc++ (GLIBCXX_3.4.32): Debian trixie or newer, not bookworm.
DISTRO="${DISTRO:-trixie}"

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" -e POSTGRES_PASSWORD=postgres -p "$PORT:5432" \
  --add-host=host.docker.internal:host-gateway "postgres:$PG-$DISTRO" >/dev/null
for _ in $(seq 1 30); do docker exec "$NAME" pg_isready -U postgres -q && break; sleep 1; done

ARCH="$(docker exec "$NAME" dpkg --print-architecture)"
DEB="wrappers-v${WRAPPERS}-pg${PG}-${ARCH}-linux-gnu.deb"
docker exec "$NAME" bash -c "
  apt-get update -qq >/dev/null &&
  apt-get install -y -qq curl ca-certificates >/dev/null 2>&1 &&
  curl -sfL -o /tmp/$DEB https://github.com/supabase/wrappers/releases/download/v${WRAPPERS}/$DEB &&
  apt-get install -y -qq /tmp/$DEB >/dev/null 2>&1"
docker exec "$NAME" psql -U postgres -Atc "select 'wrappers ' || default_version from pg_available_extensions where name = 'wrappers'"

if [[ "${1:-}" != "--no-mock" ]]; then
  cd "$(dirname "$0")/.."
  pkill -f "mock/server.py" 2>/dev/null || true
  nohup python3 mock/server.py --port 8787 --fixtures fixtures/serp > /tmp/serpapi-mock.log 2>&1 &
  sleep 1 && echo "mock serpapi on :8787"
fi
echo "export DB_URL=postgresql://postgres:postgres@127.0.0.1:$PORT/postgres CONTAINER=$NAME"
