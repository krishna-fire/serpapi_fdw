#!/usr/bin/env bash
# Load the built wrapper into a running `supabase start` database and (re)create the server.
#   scripts/load-local.sh                # uses ~/.serpapi_key for the Vault secret
#   SERPAPI_API_KEY=... scripts/load-local.sh
#   SERPAPI_FDW_VERSION=v0.1.0 ...      # release to download when dist/serpapi_fdw.wasm is absent
# Then apply the SQL layers:  scripts/apply-sql.sh
set -euo pipefail
cd "$(dirname "$0")/.."

WASM=dist/serpapi_fdw.wasm
# No local build? Fetch the published release instead (no Rust toolchain needed), checksum-verified.
# To build from source instead: scripts/build.sh (rustup) or scripts/build.sh --docker.
if [[ ! -f "$WASM" ]]; then
  REL="${SERPAPI_FDW_VERSION:-v0.1.0}"
  BASE="https://github.com/krishna247/serpapi_fdw/releases/download/$REL"
  echo "no $WASM; downloading release $REL from GitHub, can take a minute (or build it: scripts/build.sh [--docker])"
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  curl -fsSL -o "$TMP/serpapi_fdw.wasm" "$BASE/serpapi_fdw.wasm" \
    && curl -fsSL -o "$TMP/checksum.txt" "$BASE/checksum.txt" \
    || { echo "download of $REL failed; build instead: scripts/build.sh [--docker]" >&2; exit 1; }
  WANT="$(awk '/serpapi_fdw\.wasm/ {print $1; exit}' "$TMP/checksum.txt")"
  if command -v sha256sum >/dev/null; then GOT="$(sha256sum "$TMP/serpapi_fdw.wasm" | awk '{print $1}')"
  else GOT="$(shasum -a 256 "$TMP/serpapi_fdw.wasm" | awk '{print $1}')"; fi
  [[ -n "$WANT" && "$GOT" == "$WANT" ]] || { echo "checksum mismatch for $REL (want ${WANT:-?}, got $GOT)" >&2; exit 1; }
  mkdir -p dist
  install -m 644 "$TMP/serpapi_fdw.wasm" "$WASM"
  cp "$TMP/checksum.txt" dist/checksum.txt
  echo "verified sha256 $GOT -> $WASM"
fi

# Supabase local: auto-detected. Plain Postgres: set DB_URL and CONTAINER (see scripts/plain-pg-up.sh).
DB_URL="${DB_URL:-$(supabase status --output env 2>/dev/null | sed -n 's/^DB_URL=//p' | tr -d '"')}"
test -n "$DB_URL" || { echo "set DB_URL, or run inside a started supabase project" >&2; exit 1; }

CONTAINER="${CONTAINER:-$(docker ps --filter 'name=supabase_db_' --format '{{.Names}}' | head -1)}"
test -n "$CONTAINER" || { echo "set CONTAINER (the postgres docker container to copy the .wasm into)" >&2; exit 1; }

KEY="${SERPAPI_API_KEY:-$(cat "$HOME/.serpapi_key" 2>/dev/null || true)}"
test -n "$KEY" || { echo "set SERPAPI_API_KEY or put the key in ~/.serpapi_key" >&2; exit 1; }

VERSION="$(grep -m1 '^version' Cargo.toml | sed -E 's/.*"([^"]+)".*/\1/')"
# SERPAPI_API_URL=http://host.docker.internal:8787 points the wrapper at mock/server.py. On Linux the
# supabase CLI starts its containers with host.docker.internal:host-gateway, and plain-pg-up.sh does too.
API_URL="${SERPAPI_API_URL:-https://serpapi.com}"

docker cp "$WASM" "$CONTAINER:/tmp/serpapi_fdw.wasm"
docker exec "$CONTAINER" chmod 644 /tmp/serpapi_fdw.wasm   # postgres (uid 100) must be able to read it
echo "copied $WASM into $CONTAINER:/tmp/serpapi_fdw.wasm"

# The key goes into Vault via a psql variable so it never appears in SQL history or the repo.
psql "$DB_URL" -v ON_ERROR_STOP=1 -v key="$KEY" -v version="$VERSION" -v api_url="$API_URL" <<'SQL'
\i sql/00_wrappers.sql
select exists (select 1 from pg_extension where extname = 'supabase_vault') as has_vault \gset
drop server if exists serpapi cascade;
\if :has_vault
  -- Supabase: key lives in Vault. psql variables are not expanded inside dollar-quoted blocks,
  -- so keep these as plain statements.
  select vault.create_secret(:'key', 'serpapi_api_key', 'SerpApi API key for serpapi_fdw')
    where not exists (select 1 from vault.secrets where name = 'serpapi_api_key');
  select vault.update_secret(id, :'key') from vault.secrets where name = 'serpapi_api_key';
  create server serpapi foreign data wrapper wasm_wrapper options (
    fdw_package_url 'file:///tmp/serpapi_fdw.wasm',
    fdw_package_name 'serpapi:serpapi-fdw',
    fdw_package_version :'version',
    api_url :'api_url',
    api_key_name 'serpapi_api_key',
    default_gl 'in', default_hl 'en',
    default_location 'Bengaluru,Karnataka,India',
    default_google_domain 'google.co.in', default_amazon_domain 'amazon.in',
    hourly_cap '50', monthly_cap '250', max_pages '3'
  );
\else
  -- Plain Postgres: no Vault. The key is a server option (visible to superusers in pg_foreign_server),
  -- and the wrapper only honours it when serpapi.allow_plain_key is on for this database.
  select format('alter database %I set serpapi.allow_plain_key = on', current_database()) \gexec
  create server serpapi foreign data wrapper wasm_wrapper options (
    fdw_package_url 'file:///tmp/serpapi_fdw.wasm',
    fdw_package_name 'serpapi:serpapi-fdw',
    fdw_package_version :'version',
    api_url :'api_url',
    api_key :'key',
    default_gl 'in', default_hl 'en',
    default_location 'Bengaluru,Karnataka,India',
    default_google_domain 'google.co.in', default_amazon_domain 'amazon.in',
    hourly_cap '50', monthly_cap '250', max_pages '3'
  );
\endif
SQL
echo "server 'serpapi' created (file:///tmp/serpapi_fdw.wasm, v$VERSION, api_url $API_URL)"
