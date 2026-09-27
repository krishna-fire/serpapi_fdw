#!/usr/bin/env bash
# Run scripts/smoke.sql and assert the expected outcome: exactly the five deliberate errors
# (three guards + two hourly-cap hits) and no warnings. Usable locally and in CI.
#   DB_URL=... scripts/smoke-assert.sh
set -uo pipefail
cd "$(dirname "$0")/.."
DB_URL="${DB_URL:-$(supabase status --output env 2>/dev/null | sed -n 's/^DB_URL=//p' | tr -d '"')}"
test -n "$DB_URL" || { echo "set DB_URL" >&2; exit 2; }

OUT="$(mktemp)"
psql "$DB_URL" -Atc "select serpapi.reset_budget()" >/dev/null 2>&1 || true
psql "$DB_URL" -v ON_ERROR_STOP=0 -f scripts/smoke.sql > "$OUT" 2>&1
ERRORS=$(grep -c '^psql:.*ERROR' "$OUT" || true)
WARNINGS=$(grep -c 'WARNING' "$OUT" || true)
ROWS4=$(sed -n '/^== 4\./,/^== 5\./p' "$OUT" | grep -c 'fixture-shopping\|serpapi.com\|^ [0-9a-f]\{8\}' || true)
LATERAL=$(sed -n '/^== 6\./,/^== 7\./p' "$OUT" | grep -c 'boAt' || true)
REPEAT=$(sed -n '/^== 16\./,/^== 17\./p' "$OUT" | grep -c '^ *[0-9]\+$' || true)

echo "smoke: errors=$ERRORS (want 5) warnings=$WARNINGS (want 0) shopping_rows=$ROWS4 lateral_rows=$LATERAL repeated_ok=$REPEAT (want 6)"
status=0
[[ "$ERRORS" == "5" ]]   || { echo "FAIL: unexpected error count"; status=1; }
[[ "$WARNINGS" == "0" ]] || { echo "FAIL: warnings present"; status=1; }
[[ "$ROWS4" -ge 1 ]]     || { echo "FAIL: no shopping rows"; status=1; }
[[ "$LATERAL" -ge 2 ]]   || { echo "FAIL: LATERAL produced no rows"; status=1; }
[[ "$REPEAT" == "6" ]]   || { echo "FAIL: repeated calls broke (generic plan?)"; status=1; }
if [[ $status -ne 0 ]]; then
  echo "----- smoke output -----"; cat "$OUT"
fi
rm -f "$OUT"
exit $status
