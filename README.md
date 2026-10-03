# serpapi_fdw

SerpApi as Postgres functions. Live Google Shopping, Amazon, Jobs, Maps, News, or any other SerpApi engine, callable from SQL, from a Supabase app, or from `pg_cron`. The API key stays in the database, and quotas and credit caps are enforced before a request leaves it.

```sql
select title, source, extracted_price, old_price
from serpapi.google_shopping('iPhone 16');

select p.sku, s.source, s.extracted_price
from products p, lateral serpapi.google_shopping(p.query) s;   -- one search per row

select * from serpapi.budget_status();                          -- caps and your quota; costs nothing
```

```js
const { data } = await supabase.schema('serpapi').rpc('google_shopping', { q: 'iPhone 16' })
```

Built for the [SerpApi India Hackathon 2026](https://serpapi.github.io/serpapi-india-hackathon-2026/), Open-Source Integrations track.

## Why

A Supabase app has auth and a database, and often no server of its own. Search needs a SerpApi key, and a key shipped to the browser is visible to every user. Hiding it behind a function is the easy part; the hard part is that every user who can trigger a search can spend your credits.

serpapi_fdw puts search next to your data and your access rules:

- **The key lives in Vault.** The app calls a Postgres function; only the wrapper ever reads the key.
- **Anonymous callers are refused.** Signed-in users get a daily quota (20 searches by default).
- **Caps fail closed.** Hourly and monthly credit caps are checked inside the wrapper, before the HTTP request.
- **Results are rows.** Join them to your tables, keep them, or schedule them with `pg_cron`. No extra service.

## How it works

- **`serpapi_fdw.wasm`**: a [Supabase Wrappers](https://fdw.dev) foreign data wrapper in Rust, compiled to Wasm and run inside Postgres. It reads the key from Vault, builds canonical requests, follows pagination, parses JSON into typed columns, and keeps the account-wide credit budget. Its foreign tables live in a private schema nobody is granted.
- **Generated SQL functions**: one `security definer` function per engine, with named, defaulted arguments, a per-caller daily quota, a request log, and replays from SerpApi's archive.

The wrapper, the foreign tables and the functions are all generated from [`catalog/engines.json`](catalog/engines.json) by `scripts/gen.py`, so adding an engine is a catalog entry. Design and request flow: [docs/architecture.md](docs/architecture.md). Every argument and column: [docs/engines.md](docs/engines.md).

## Functions

| Function | Engine | Notes |
|---|---|---|
| `google(q, …)`, `google_light(q, …)` | `google`, `google_light` | organic results; `start` pagination |
| `google_shopping(q, …)` | `google_shopping` | Indian merchants with `gl=in`; `old_price` is the strikethrough |
| `amazon(q, amazon_domain => 'amazon.in', …)` | `amazon` | ASIN, `bought_last_month`, `sponsored`; `page` pagination |
| `google_jobs(q, location => …, pages => 2)` | `google_jobs` | `apply_options`; token pagination |
| `google_maps(q, ll => '@12.97,77.59,14z')` | `google_maps` | `data_id` feeds reviews; `start` pagination |
| `google_maps_reviews(data_id => …)` | `google_maps_reviews` | translated snippets; token pagination |
| `google_news(q, hl => 'hi')` | `google_news` | regional editions |
| `search(engine, params jsonb)` | any | the whole response as `jsonb`, one row per page |
| `replay_<engine>(search_id)`, `replay(search_id)` | archive | re-read a past search, free for 31 days |
| `search_md(engine, params)` | any | one search, returned as Markdown from the archive (for LLM prompts) |
| `replay_md(search_id)` | archive | a past search as Markdown, free |
| `account()` | account | credits left; never returns the key |
| `budget_status()` | none | caps and your quota; no HTTP |

All live in the `serpapi` schema. `pages => n` follows pagination where the engine has it, up to the server's `max_pages`.

## How it uses SerpApi

| SerpApi API | Endpoint | Used for |
|---|---|---|
| Search API | `/search.json` | every live row; the only call that spends credits |
| Search Archive API | `/searches/{search_id}.json` | `replay_*`: re-reading a search without running it again |
| Search Archive API (Markdown) | `/searches/{search_id}.md` | `search_md`, `replay_md` |
| Account API | `/account.json` | `account()`, with the key stripped from the row |

The wrapper keeps the bill down in three ways. Requests are canonical (unset arguments omitted, server defaults filled in, parameters sorted), so a repeat within the hour hits SerpApi's free cache; `no_cache` is never sent. Typed functions send a `json_restrictor`, so only the results block and its metadata come back. And every successful `/search.json` call counts against the caps; cached responses look identical, so the count errs high. Archive and account calls are free and uncounted.

No SDK or MCP server is involved: the wrapper runs inside Postgres, where there is no Python or Node runtime, so it builds requests itself (`src/request.rs`) and sends them through the Wrappers host's HTTP client.

## Try it in ten minutes

Offline: recorded fixtures served by a local mock, no key, no credits. Needs Docker (running), the [Supabase CLI](https://supabase.com/docs/guides/cli), `psql` and `python3`.

```bash
git clone https://github.com/krishna247/serpapi_fdw && cd serpapi_fdw
scripts/dev-up.sh            # local Supabase (Postgres 17, Wrappers, Auth), the mock on :8787, a demo user
SERPAPI_API_URL=http://host.docker.internal:8787 SERPAPI_API_KEY=mock-key scripts/load-local.sh
scripts/apply-sql.sh
scripts/smoke-assert.sh      # 17 checks
```

No Rust needed: `load-local.sh` downloads the release `.wasm` and verifies its checksum. To build it yourself, run `scripts/build.sh` (Rust 1.97.1 and `cargo-component` 0.21.1) or `scripts/build.sh --docker` first. Then try it in `psql "$(supabase status -o env | sed -n 's/^DB_URL=//p' | tr -d '"')"`:

```sql
select source, extracted_price, old_price from serpapi.google_shopping('boAt Airdopes 141');
select asin, extracted_price, extracted_old_price from serpapi.amazon('iPhone');
select * from serpapi.budget_status();
```

Over HTTP, the functions are PostgREST RPC calls with `Content-Profile: serpapi`. Anonymous calls get `401`; the demo user (`priya@example.com` / `serpapi-demo`) gets rows. [`demo/playground/index.html`](demo/playground/index.html) is a static page that does this: copy `config.example.js` to `config.js`, set `url` to `http://127.0.0.1:54321` and `anonKey` to `ANON_KEY` from `supabase status -o env`, and open the file.

For live data, put your key in `~/.serpapi_key`, run `scripts/dev-up.sh --no-mock`, then `scripts/load-local.sh` without `SERPAPI_API_URL`. On Linux, if `host.docker.internal` does not resolve, use the Docker bridge address (often `http://172.17.0.1:8787`).

## Install

On hosted Supabase, or any Postgres with Wrappers 0.5 or later:

```sql
create extension if not exists wrappers with schema extensions;
create foreign data wrapper wasm_wrapper handler wasm_fdw_handler validator wasm_fdw_validator;

select vault.create_secret('<your serpapi key>', 'serpapi_api_key');

create server serpapi foreign data wrapper wasm_wrapper options (
  fdw_package_url 'https://github.com/krishna247/serpapi_fdw/releases/download/v0.1.0/serpapi_fdw.wasm',
  fdw_package_name 'serpapi:serpapi-fdw',
  fdw_package_version '0.1.0',
  fdw_package_checksum 'e91ef82b1cfd1c6bd045982c4848e76c0bc78eff57903c84d7d172181d84e54f',
  api_key_name 'serpapi_api_key',
  default_gl 'in', default_location 'Bengaluru,Karnataka,India', default_amazon_domain 'amazon.in',
  hourly_cap '50', monthly_cap '250', max_pages '3'
);
```

Then apply `sql/10_private.sql`, `sql/20_generated.sql` and `sql/30_public.sql` (`scripts/apply-sql.sh`), and add `serpapi` to the project's exposed schemas for RPC. `scripts/load-hosted.sh` runs the SQL above with the checksum fetched from the release. The caps above match SerpApi's free plan (250 searches a month, 50 an hour).

On some hosted projects the second line fails with `permission denied to create foreign-data wrapper`, because a grant Supabase applies at provisioning is missing ([supabase/supabase#46480](https://github.com/supabase/supabase/issues/46480), details in [docs/notes.md](docs/notes.md)). Only Supabase can repair such a project.

## Where it runs

| Platform | Key storage | Setup |
|---|---|---|
| Supabase, hosted | Vault | `scripts/load-hosted.sh` (see the caveat above) |
| Supabase, local | Vault | `scripts/dev-up.sh` |
| Postgres 14–18, self-hosted (Debian trixie, Ubuntu 24.04+) | `api_key` server option, gated by `serpapi.allow_plain_key` | the [Wrappers .deb](https://github.com/supabase/wrappers/releases), `scripts/plain-pg-up.sh` |
| RDS, Cloud SQL and other managed Postgres | — | not installable; query a sidecar with `postgres_fdw` ([docs/managed-postgres.md](docs/managed-postgres.md)) |

The same wrapper, SQL and 17-check suite run on every supported row; CI runs them on stock Postgres 17.

## Example: a nightly price ledger

`sql/40_snapshots.sql` and `sql/50_cron.sql` record iPhone prices every night at 02:30 IST: Amazon.in for "iPhone" (2 credits) and Google Shopping for "iPhone 16" (1 credit), keyed by ASIN or Google product ID, with sponsored listings skipped. On a sale day, `strikethrough_forensics(day)` compares each "was" price with the highest real price seen in the previous twelve nights.

```sql
select cron.schedule('serpapi-nightly-prices', '0 21 * * *', $$ call serpapi.snapshot_prices() $$);
select * from public.strikethrough_forensics('2026-10-09') where inflated;
```

## Limits

- What Google returns for India (merchants, Flipkart-only listings) is Google's call; the wrapper reports what SerpApi returns.
- Google Shopping ignores pagination. Google Jobs fails intermittently upstream; retry.
- Empty results are zero rows and a `NOTICE`; SerpApi still charges a credit.
- The host HTTP client has no timeout; `statement_timeout` on every function is the bound.
- Budget writes are skipped in read-only transactions, so call the RPC functions with POST.
- Row-level security does not apply to foreign tables, which is why they are private and the functions are `security definer`.

Issues found in Wrappers and SerpApi along the way are written up in [docs/notes.md](docs/notes.md), to be filed upstream.

## Provenance

Krishna Janaswamy, Bengaluru. A new project, started on 2026-09-26 for the hackathon. MIT licensed.

AI use: Claude Code (Anthropic) for design, Rust and SQL scaffolding, tests, docs and the demo-video tooling. The video's voiceover is ElevenLabs text-to-speech; earlier drafts used Kokoro-82M and Google Chirp 3 HD.
