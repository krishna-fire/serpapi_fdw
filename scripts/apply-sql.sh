#!/usr/bin/env bash
# Apply the SQL layers (after the server exists). Idempotent where Postgres allows; the
# generated layer is dropped and recreated so catalog changes propagate.
set -euo pipefail
cd "$(dirname "$0")/.."

DB_URL="${DB_URL:-$(supabase status --output env 2>/dev/null | sed -n 's/^DB_URL=//p' | tr -d '"')}"
test -n "$DB_URL" || { echo "set DB_URL or run inside a supabase project" >&2; exit 1; }

python3 scripts/gen.py

psql "$DB_URL" -v ON_ERROR_STOP=1 <<'SQL'
\i sql/10_private.sql
-- generated layer: recreate from scratch
drop schema if exists serpapi cascade;
create schema serpapi;
revoke all on schema serpapi from public;
do $$
declare r record;
begin
  for r in select foreign_table_schema s, foreign_table_name t from information_schema.foreign_tables where foreign_table_schema = 'serpapi_private' loop
    execute format('drop foreign table if exists %I.%I', r.s, r.t);
  end loop;
end $$;
\i sql/20_generated.sql
\i sql/30_public.sql
\i sql/40_snapshots.sql
SQL
echo "applied 10/20/30/40. Schedule the ledger with: psql \"\$DB_URL\" -f sql/50_cron.sql"
