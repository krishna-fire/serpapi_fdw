#!/usr/bin/env bash
# Install the wrapper into a hosted Supabase project from a GitHub release URL.
#   PROJECT_REF=yaqhoyzxwwynwwjotmgh RELEASE=v0.1.0-rc1 scripts/load-hosted.sh
# Needs: ~/.supabase-db-password (or SUPABASE_DB_PASSWORD), ~/.serpapi_key (or SERPAPI_API_KEY).
# Uses the direct IPv6 host by default; set POOLER=1 to use the session pooler on IPv4-only networks.
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT_REF="${PROJECT_REF:?set PROJECT_REF (the ref in the project URL)}"
RELEASE="${RELEASE:-v0.1.0}"
REGION="${REGION:-ap-south-1}"
PW="${SUPABASE_DB_PASSWORD:-$(cat "$HOME/.supabase-db-password" 2>/dev/null || true)}"
test -n "$PW" || { echo "put the database password in ~/.supabase-db-password" >&2; exit 1; }
PW="$(printf '%s' "$PW" | python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.stdin.read().strip(), safe=""))')"   # URL-safe
KEY="${SERPAPI_API_KEY:-$(cat "$HOME/.serpapi_key" 2>/dev/null || true)}"
test -n "$KEY" || { echo "put the SerpApi key in ~/.serpapi_key" >&2; exit 1; }

if [[ "${POOLER:-0}" == "1" ]]; then
  export DB_URL="postgresql://postgres.${PROJECT_REF}:${PW}@aws-1-${REGION}.pooler.supabase.com:5432/postgres"
else
  export DB_URL="postgresql://postgres:${PW}@db.${PROJECT_REF}.supabase.co:5432/postgres"
fi

URL="https://github.com/krishna-fire/serpapi_fdw/releases/download/${RELEASE}/serpapi_fdw.wasm"
SUM="$(curl -sfL "https://github.com/krishna-fire/serpapi_fdw/releases/download/${RELEASE}/checksum.txt" | awk '{print $1}')"
test -n "$SUM" || { echo "could not fetch checksum for $RELEASE" >&2; exit 1; }
VERSION="$(grep -m1 '^version' Cargo.toml | sed -E 's/.*"([^"]+)".*/\1/')"
echo "release $RELEASE  sha256 $SUM  package version $VERSION"

# The key and password never appear in the SQL text: psql variables, and a URL only in the env.
psql "$DB_URL" -v ON_ERROR_STOP=1 -v key="$KEY" -v url="$URL" -v sum="$SUM" -v version="$VERSION" <<'SQL'
\i sql/00_wrappers.sql
select vault.create_secret(:'key', 'serpapi_api_key', 'SerpApi API key for serpapi_fdw')
  where not exists (select 1 from vault.secrets where name = 'serpapi_api_key');
select vault.update_secret(id, :'key') from vault.secrets where name = 'serpapi_api_key';
drop server if exists serpapi cascade;
create server serpapi foreign data wrapper wasm_wrapper options (
  fdw_package_url :'url',
  fdw_package_name 'serpapi:serpapi-fdw',
  fdw_package_version :'version',
  fdw_package_checksum :'sum',
  api_key_name 'serpapi_api_key',
  default_gl 'in', default_hl 'en',
  default_location 'Bengaluru,Karnataka,India',
  default_google_domain 'google.co.in', default_amazon_domain 'amazon.in',
  hourly_cap '50', monthly_cap '250', max_pages '3'
);
SQL
echo "server 'serpapi' created on $PROJECT_REF from $URL"
echo "next: DB_URL is exported by this script only; run:  DB_URL='<same url>' scripts/apply-sql.sh"
