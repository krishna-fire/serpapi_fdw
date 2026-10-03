#!/usr/bin/env bash
# demo/rpc.sh <anon|user> <function> '<json>'  — call a serpapi.* function through PostgREST, pretty-printed
role="$1"; fn="$2"; body="${3:-{\}}"
case "$role" in anon) tok="$ANON_JWT";; user) tok="$USER_JWT";; *) echo "role anon|user" >&2; exit 2;; esac
base="${REST_URL:-http://host.docker.internal:54321}"
curl -s -X POST "$base/rest/v1/rpc/$fn" -H "apikey: $tok" -H "Authorization: Bearer $tok" \
  -H "Content-Profile: serpapi" -H "Content-Type: application/json" -d "$body" \
| python3 -c 'import json,sys
d=json.load(sys.stdin)
print("\n".join(json.dumps(x) for x in d) if isinstance(d, list) else json.dumps(d, indent=2))'
