#!/usr/bin/env bash
# Create (idempotently) the playground's demo user in local Supabase Auth, email already confirmed.
#   scripts/demo-user.sh                                  # priya@example.com / serpapi-demo
#   DEMO_EMAIL=you@example.com DEMO_PASSWORD=... scripts/demo-user.sh
# Uses the local service_role key from `supabase status`; local stacks only.
set -euo pipefail
cd "$(dirname "$0")/.."

EMAIL="${DEMO_EMAIL:-priya@example.com}"
PASSWORD="${DEMO_PASSWORD:-serpapi-demo}"
ENV="$(supabase status --output env 2>/dev/null || true)"
API="$(sed -n 's/^API_URL=//p' <<<"$ENV" | tr -d '"')"
SRK="$(sed -n 's/^SERVICE_ROLE_KEY=//p' <<<"$ENV" | tr -d '"')"
DB_URL="$(sed -n 's/^DB_URL=//p' <<<"$ENV" | tr -d '"')"
[[ -n "$API" && -n "$SRK" ]] || { echo "supabase not running (no API_URL / SERVICE_ROLE_KEY)" >&2; exit 1; }

for _ in $(seq 1 30); do curl -sf -m 3 "$API/auth/v1/health" -H "apikey: $SRK" >/dev/null && break; sleep 2; done
BODY="$(printf '{"email":"%s","password":"%s","email_confirm":true}' "$EMAIL" "$PASSWORD")"
CODE="$(curl -s -o /dev/null -w '%{http_code}' -m 10 -X POST "$API/auth/v1/admin/users" \
  -H "apikey: $SRK" -H "Authorization: Bearer $SRK" -H "Content-Type: application/json" -d "$BODY")"
case "$CODE" in
  200|201) echo "demo user $EMAIL created (password: $PASSWORD)" ;;
  422)     # exists: reset the password so the documented one always works
           psql "$DB_URL" -qAt -v ON_ERROR_STOP=1 -v email="$EMAIL" -v pw="$PASSWORD" >/dev/null <<'SQL'
update auth.users set encrypted_password = extensions.crypt(:'pw', extensions.gen_salt('bf')),
       email_confirmed_at = coalesce(email_confirmed_at, now())
 where email = :'email';
SQL
           echo "demo user $EMAIL exists (password reset to: $PASSWORD)" ;;
  *)       echo "creating demo user failed (HTTP $CODE)" >&2; exit 1 ;;
esac
