# Notes for SerpApi and Supabase

Concrete observations made while building `serpapi_fdw`, with the workaround used. Each will be
filed as an issue where one does not already exist; links are added as they are filed.

## Supabase Wrappers (Wasm host)

0. **`invalid WebAssembly component` is also what you get when the file simply cannot be read.**
   `Component::from_file(...).map_err(|_| WasmFdwError::InvalidWasmComponent)` collapses I/O errors
   (here: a `file://` package copied into the container as mode 0600 owned by another uid, unreadable
   by `postgres`) into the same message as a genuinely malformed component. That cost an afternoon:
   the same bytes compiled fine under `wasmtime 36.0.7` on the host, `wasm-tools validate` passed,
   and a `chmod 644` fixed it. *Suggestion:* keep the source error in the message (or log it at
   `DEBUG`), and have the `file://` loader check readability up front and say "permission denied".
0b. **The released `wrappers` .deb needs `GLIBCXX_3.4.32`**, so it loads on Debian trixie / Ubuntu 24.04
   but fails on the default `postgres:17` (bookworm) image with `could not load library … version
   'GLIBCXX_3.4.32' not found`. Worth a line on the release page; `postgres:17-trixie` works.
   Also: after `create extension wrappers with schema extensions` on plain Postgres, the handler must
   be referenced schema-qualified (`extensions.wasm_fdw_handler`) because `extensions` is only on
   the default `search_path` on Supabase.
0c. **Hosted Supabase: `create foreign data wrapper` is superuser-only, and the grant that lets
   `postgres` do it is applied by Supabase's provisioning pipeline, not by the extension.** On a
   freshly created free project (Postgres 17.6, Wrappers 0.5.7) both psql and the dashboard SQL
   editor returned `42501 permission denied to create foreign-data wrapper … Must be superuser`;
   `supautils.privileged_role` points at a role that does not exist in the database, and `postgres`
   holds no membership that could stand in. This is the symptom tracked in supabase/supabase#46480
   (open, June 2026) and PR #46533. Nothing a user can run fixes it. *Suggestion:* make the FDW
   creation part of `create extension wrappers` (run as `supabase_admin`, which already happens for
   privileged extensions) so third-party Wasm wrappers work wherever the extension does.
1. **429 retries ignore `Retry-After`, and there is no request timeout.** The host wraps
   `reqwest` with `reqwest_retry` (`max_retries(3)`, exponential backoff) and no `timeout`
   ([host/http.rs](https://github.com/supabase/wrappers/blob/main/wrappers/src/fdw/wasm_fdw/host/http.rs)).
   A guest cannot opt out, so a rate-limited scan hammers the upstream three more times.
   *Workaround:* the wrapper enforces its own hourly/monthly caps before issuing the call, and
   every SQL function sets `statement_timeout`.
2. **`error_for_status` formats the full URL into the error**, including query-string API keys.
   For APIs that authenticate via `?api_key=` this puts the secret in Postgres error text and logs.
   *Workaround:* never call it; map status codes in the guest and never report URLs.
3. **The public template `postgres-wasm-fdw` pins WIT v1** (`supabase:wrappers@0.1.0`), which has
   no `import_foreign_schema` and lacks `get_vault_secret_by_name` / `query_setting`. New wrappers
   should start from `wasm-wrappers/fdw/helloworld_fdw` in the main repo (WIT v2).
4. **No SPI from a Wasm guest**, so per-user quotas, caches and logs have to live in SQL around the
   foreign table. The only durable guest-writable state is `stats.set_metadata` — enough for the
   account-wide budget, but writes are skipped in read-only transactions (PostgREST GET).
5. **Every qual is rechecked locally**, so parameter columns must be echoed back verbatim in every
   row or the executor filters everything out after the credit has been spent. This deserves a
   line in the Wasm FDW guide; it is the first thing every API-as-table wrapper gets wrong.

## SerpApi

1. **Google Jobs pagination is token-only** (`next_page_token`); `start` is discontinued. Google
   Shopping ignores `start` entirely (~40 results per request). Documenting the per-engine
   pagination kind in one machine-readable place would help integrations; `catalog/engines.json`
   is ours.
2. **Empty results cost a credit** and arrive as HTTP 200 with `"error": "Google hasn't returned
   any results…"`. The wrapper surfaces them as zero rows plus a `NOTICE`, and counts the credit.
3. **Cached responses are indistinguishable** from fresh ones in the JSON, so a client cannot
   know whether a call was free. A `search_metadata.cached: true` flag would let budgets be exact.
4. **`hl=kn` on Google News falls back to Hindi** silently (no Kannada edition). Worth a note on
   the News API page.
5. **India-specific:** Google Hotels via SerpApi omits Indian OTAs (public roadmap #2836); Google
   Events API is deprecated (Aug 2026) although the hackathon page still lists it; Local Services
   is US-only.

## Postgres

- Row-level security cannot be enabled on foreign tables (`ATT_TABLE | ATT_PARTITIONED_TABLE`
  only in `tablecmds.c`). Hence private schema + `security definer` functions, as Supabase's
  own Wrappers security guide recommends.
- A `security definer` function is not inlined, so the foreign scan runs with its arguments as
  bound parameters; Wrappers ≥ 0.6.1 rescans correctly when parameters change (PR #587).

## Local wasm lives in the container's /tmp (2026-09-27)

`scripts/load-local.sh` copies `dist/serpapi_fdw.wasm` to `/tmp/serpapi_fdw.wasm` inside the db
container and points `fdw_package_url` at `file:///tmp/...`. That path is not on a volume: any
`supabase stop` + `start` recreates the container and every call then fails with
`invalid WebAssembly component` (the host reports a missing file with the same message as a corrupt
one). Re-run `docker cp dist/serpapi_fdw.wasm supabase_db_<project>:/tmp/serpapi_fdw.wasm` and
`chmod 644` it, or use the `--docker`-free alternative of serving the file over HTTP from the host.

## Grants (2026-09-27)

Procedures default to PUBLIC execute in Postgres, so `40_snapshots.sql` now revokes
`serpapi.snapshot_prices(date)` from public. `30_public.sql` grants signed-in Supabase users
(`authenticated`) every typed engine function, its `replay_*` twin and the Markdown pair, all of
which are metered by the per-caller daily quota; the generic `search`/`replay` (any engine) stay
owner/service_role only. Anonymous callers keep only `budget_status()`.
