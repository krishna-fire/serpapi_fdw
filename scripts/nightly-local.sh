#!/usr/bin/env bash
# Run the nightly ledger against a local database (fallback when no hosted pg_cron exists).
# Spends ~3 SerpApi credits per run (see public.tracked_searches). Meant for launchd/cron:
#   DB_URL=postgresql://postgres:postgres@127.0.0.1:55433/postgres scripts/nightly-local.sh
set -uo pipefail
cd "$(dirname "$0")/.."
DB_URL="${DB_URL:?set DB_URL}"
LOG="${LOG:-/tmp/serpapi-fdw-nightly.log}"
{
  echo "== $(date -u +%FT%TZ) nightly snapshot"
  psql "$DB_URL" -v ON_ERROR_STOP=0 -Atc "call serpapi.snapshot_prices();" \
    -c "select 'run ' || id || ': searches=' || searches || ' rows=' || rows || ' errors=' || errors from public.snapshot_runs order by id desc limit 1;" \
    -c "select scope || '/' || \"window\" || ' ' || used || '/' || cap from serpapi.budget_status();"
} >> "$LOG" 2>&1
tail -4 "$LOG"
