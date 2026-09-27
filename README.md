# serpapi_fdw

**SerpApi as Postgres functions for Supabase.** Live Google Shopping, Amazon.in, Google Jobs, Maps, News and every other SerpApi engine become SQL you can join, schedule and expose through PostgREST — with a credit budget enforced inside the wrapper.

```sql
select title, source, extracted_price, old_price
from serpapi.google_shopping('boAt Airdopes 141');           -- gl=in from the server defaults

select p.sku, s.source, s.extracted_price
from products p, lateral serpapi.google_shopping(p.query) s; -- one search per row, visibly

select * from serpapi.budget_status();                        -- used / cap / resets_at, costs nothing
```

Built for the [SerpApi India Hackathon 2026](https://serpapi.github.io/serpapi-india-hackathon-2026/) (Open-Source Integrations). The bundled example, **Strikethrough**, snapshots ten products nightly through the wrapper and shows on Big Billion Days which "70% off" strikethrough prices were manufactured in the days before the sale.

> Status: under construction (Sep 27 → Oct 10, 2026). See [docs/architecture.md](docs/architecture.md) and [docs/engines.md](docs/engines.md).

## Why

Every SerpApi tutorial ends with "export to Sheets". The analysis happens in a query engine, and for a Supabase app that engine is already Postgres. A search API is not a table, though, so this project has two layers:

* **`serpapi_fdw.wasm`** — a [Supabase Wrappers](https://fdw.dev) Wasm foreign data wrapper. It owns HTTP, the API key (from Vault), canonical parameters (so repeats hit SerpApi's free one-hour cache), typed parsing, pagination, and an account-wide hourly/monthly credit cap persisted in the wrapper's metadata. Its foreign tables live in a private schema nobody is granted.
* **Generated SQL functions** — one `security definer` function per engine with named, defaulted arguments, a per-caller daily quota, a request log, and `replay_*` functions that re-read past searches from SerpApi's archive for free.

The result: named arguments instead of `WHERE q = …`, an explicit `LATERAL` when you mean one call per row, and nothing an app can call that spends credits without a quota check.

## Where it runs

| Platform | Wrappers host | Key storage | Status |
|---|---|---|---|
| Supabase hosted | preinstalled | Vault (`api_key_name`) | install from the release URL with `scripts/load-hosted.sh`. Caveat: `create foreign data wrapper` needs a privilege Supabase grants to `postgres` during provisioning; on projects where it is missing (see [supabase/supabase#46480](https://github.com/supabase/supabase/issues/46480), typically restored or unpaused ones) every client including the SQL editor gets `permission denied to create foreign-data wrapper`, and only Supabase can fix the project |
| Supabase local (`supabase start`) | preinstalled | Vault | `scripts/dev-up.sh` |
| Self-hosted Postgres 14–18 (Debian trixie / Ubuntu 24.04+, amd64/arm64) | [`wrappers` .deb from the Supabase releases](https://github.com/supabase/wrappers/releases) | plain `api_key` server option, gated by `serpapi.allow_plain_key` | `scripts/plain-pg-up.sh`, verified with the same 17-check suite |
| Managed clouds that forbid third-party extensions (RDS, Cloud SQL, …) | not installable | — | federate to a sidecar with `postgres_fdw` / `dblink` (below) |

Same wrapper, same SQL, same behaviour on all supported rows; the install scripts detect Vault and the Supabase roles and adapt.

### From RDS or any managed Postgres: a sidecar

RDS for PostgreSQL and Aurora can be given outbound network access (a security-group egress rule, NAT gateway or VPC endpoint, as their `aws_lambda` setup describes), but their supported-extension lists contain nothing that issues HTTP from SQL: no `http`, `pg_net`, `wrappers`, or untrusted procedural languages, and `pg_tle` allows only trusted ones ([RDS list](https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-extensions.html), [Aurora list](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraPostgreSQLReleaseNotes/AuroraPostgreSQL.Extensions.html)). So the wrapper cannot be installed there. Two routes remain. The AWS-native one is `aws_lambda.invoke` (synchronous, returns the Lambda's JSON) with a Lambda that calls SerpApi; that is a separate integration and out of scope here. The one that reuses this project unchanged: RDS ships `postgres_fdw` and `dblink`, so run `serpapi_fdw` in a sidecar (a free Supabase project or a small container) and let the managed database query it. Joins, snapshots and quotas stay next to your data; only the search hop leaves.

```sql
-- on RDS
create extension postgres_fdw;
create server serpapi_sidecar foreign data wrapper postgres_fdw
  options (host 'sidecar.example.com', port '5432', dbname 'postgres');
create user mapping for current_user server serpapi_sidecar options (user 'app', password '…');

-- table style: quals are pushed to the sidecar, whose wrapper runs exactly one search
import foreign schema serpapi_private limit to (google_shopping) from server serpapi_sidecar into sidecar;
select source, extracted_price from sidecar.google_shopping
where q = 'boAt Airdopes 141' and gl = '' and hl = '' and location = '' and google_domain = ''
  and min_price = -1 and max_price = -1 and sort_by = '' and on_sale = false and num = -1 and pages = 1;

-- function style: named arguments, quota and log on the sidecar
select * from dblink('serpapi_sidecar', $$ select source, extracted_price from serpapi.google_shopping('boAt Airdopes 141') $$)
  as t(source text, extracted_price numeric);
```

Verified against a contrib-only Postgres federating to the local Supabase stack: rows come back, `EXPLAIN VERBOSE` shows `q = …` in the remote SQL, and the sidecar's guards surface as errors on the RDS side.

## Install (hosted Supabase or any Postgres with Wrappers ≥ 0.5)

```sql
-- 1. once per database
create extension if not exists wrappers with schema extensions;
create foreign data wrapper wasm_wrapper handler wasm_fdw_handler validator wasm_fdw_validator;

-- 2. the key goes in Vault, never in SQL you commit
select vault.create_secret('<your serpapi key>', 'serpapi_api_key');

-- 3. the server (values from the GitHub release's README.txt)
create server serpapi foreign data wrapper wasm_wrapper options (
  fdw_package_url 'https://github.com/krishna-fire/serpapi_fdw/releases/download/v0.1.0/serpapi_fdw.wasm',
  fdw_package_name 'serpapi:serpapi-fdw',
  fdw_package_version '0.1.0',
  fdw_package_checksum '<sha256>',
  api_key_name 'serpapi_api_key',
  default_gl 'in', default_location 'Bengaluru,Karnataka,India', default_amazon_domain 'amazon.in',
  hourly_cap '50', monthly_cap '250', max_pages '3'
);
```

Then apply `sql/10_private.sql`, `sql/20_generated.sql`, `sql/30_public.sql` (as migrations or with `psql -f`). That creates the private foreign tables via `import foreign schema`, the public functions, quotas and the log. Add `serpapi` to your project's exposed API schemas if you want PostgREST RPC.

Free SerpApi accounts get 250 searches a month at 50 per hour; the server options above mirror that.

## Local development

```bash
scripts/dev-up.sh                    # Postgres 17 + Wrappers 0.6.2, PostgREST, Kong, and the fixture mock on :8787
scripts/build.sh                     # or scripts/build.sh --docker if you have no Rust toolchain (13 s native)
SERPAPI_API_URL=http://host.docker.internal:8787 SERPAPI_API_KEY=mock-key scripts/load-local.sh
scripts/apply-sql.sh                 # 10/20/30/40: functions, quotas, log, the Strikethrough ledger
psql "$(supabase status -o env | sed -n 's/^DB_URL=//p' | tr -d '"')" -f scripts/smoke.sql
```

That runs entirely offline against recorded fixtures (no key, no credits). For live data, put your key in `~/.serpapi_key`, run `scripts/dev-up.sh --no-mock`, and call `scripts/load-local.sh` without `SERPAPI_API_URL`. `scripts/smoke.sql` is the 17-check acceptance suite (typed functions, echo-back, LATERAL, pagination, replay, account, budget, guards, repeated calls, cap fail-closed).

Toolchain: rustup 1.97.1, `cargo-component` 0.21.1 (`cargo install --locked cargo-component --version 0.21.1`). On macOS, if `ld: library 'System' not found`, export `SDKROOT="$(xcrun --show-sdk-path)"`; `scripts/build.sh` does this for you.

## What you get

| Function | Engine | Notes |
|---|---|---|
| `serpapi.google(q, …)` / `google_light` | organic results | `start` pagination |
| `serpapi.google_shopping(q, …)` | Shopping | `gl=in` returns Indian merchants; `old_price` is the strikethrough |
| `serpapi.amazon(q, amazon_domain => 'amazon.in', …)` | Amazon | `bought_last_month`, `sponsored` |
| `serpapi.google_jobs(q, location => …, pages => 2)` | Jobs | token pagination, `apply_options` |
| `serpapi.google_maps(q, ll => '@12.97,77.59,14z')` | Maps | `data_id` feeds reviews |
| `serpapi.google_maps_reviews(data_id => …)` | Reviews | `contributor_id`, translated snippets |
| `serpapi.google_news(q, hl => 'hi')` | News | regional editions |
| `serpapi.search(engine, params jsonb)` | any of ~120 engines | one row per page, `result jsonb` |
| `serpapi.search_md(engine, params)` | any | the same search as Markdown, fetched free from the archive |
| `serpapi.replay_<engine>(search_id)` / `serpapi.replay(search_id)` | archive | free for 31 days |
| `serpapi.account()` | account | live credits left; never returns the key |
| `serpapi.budget_status()` | — | wrapper caps + your daily quota, no HTTP |

Full argument lists: [docs/engines.md](docs/engines.md). Add an engine by editing `catalog/engines.json` and running `scripts/gen.py`; the wrapper, the DDL and the functions are all generated from it.

## Guards

- `q` (or the engine's required parameter) is required; the wrapper refuses to call SerpApi without it.
- Only `=` on parameter columns (`IN (...)` on `q`); `pages` is capped by `max_pages`.
- Hourly and monthly caps live in the wrapper and fail closed before the HTTP call.
- A per-caller daily quota (`serpapi_private.settings`) applies to app users; `postgres` / `service_role` are exempt.
- Errors never contain the request URL, so the key cannot leak through Postgres logs or a screen recording.
- Empty results are zero rows plus a `NOTICE` (SerpApi still charges one credit for them).

## Strikethrough (the example)

```sql
call serpapi.snapshot_prices();                                   -- or via pg_cron, sql/50_cron.sql
select * from public.strikethrough_forensics('2026-10-09') where inflated;
```

`public.tracked_searches` holds two searches: Amazon.in for "iPhone" (two pages, every current model and variant with its ASIN, price and strikethrough, 2 credits a night) and Google Shopping for "iPhone 16" (cross-merchant rows keyed by Google's product ID, 1 credit a night). `snapshot_prices()` keys every row by ASIN or product ID, filters titles with a regex, skips sponsored listings, and commits per search so one flaky engine does not lose the night. `strikethrough_forensics(day)` compares each product's sale-day "was" price against the maximum real price seen in the previous twelve nights. A free-text query alone is the wrong identity for price tracking: the first live test for a pair of earbuds returned forty rows of cases, covers and a clone, and not one listing of the earbuds themselves.

## Limits

- Indian OTAs, Flipkart-only listings and some merchants appear or not at Google's discretion; the wrapper reports what SerpApi returns.
- Google Shopping ignores `start`; `pages` has no effect there. Google Jobs fails intermittently upstream (Sep 2026) — retry.
- The host HTTP client has no timeout and retries 429 three times; `statement_timeout` (set on every function) is the wall-clock bound.
- Metadata (budget) writes are skipped inside read-only transactions, so expose RPC functions as POST.
- Row-level security cannot be applied to foreign tables; that is why they are private and the functions are `security definer`.

## Notes for SerpApi / Supabase

Filed while building: see `docs/notes.md` (host retries on 429 ignore `Retry-After`; the Wasm FDW template pins the v1 interface without `import foreign schema`; Jobs pagination is token-only).

## Provenance

Built by Krishna Janaswamy (Bengaluru) with Claude Code for design, Rust/SQL scaffolding, tests and docs. Every module is small enough to explain in a functionality check. MIT.
