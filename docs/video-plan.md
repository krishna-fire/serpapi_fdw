# Demo video plan (target 2:40, hard limit 3:00)

Rules that shape it: screen recording, under three minutes, the project **running locally**, core
functionality visibly working, link opens without sign-in. Narration optional; speed-ups allowed;
production quality explicitly does not count. Judges watch dozens of these: the first 15 seconds
decide whether they lean in, so the finished result comes first and the setup comes second.

Everything below runs on the local stack (`scripts/dev-up.sh --no-mock`, key in `~/.serpapi_key`)
against the real SerpApi, pre-warmed within the hour so re-takes hit SerpApi's cache for free.
Credit budget for the recording day: about 6 fresh searches, approved separately before recording.

## Layout

Two panes, one terminal: left `psql` (font 16, dark), right a tail of the request log
(`watch -n1 'psql ... -c "select at::time, engine, params->>''q'', rows, elapsed_ms from serpapi.request_log limit 6"'`).
A single title card at the start and an end card; nothing else edited. Optional narration.

## Shot list

| Time | On screen | What it proves (criterion) |
|---|---|---|
| 0:00–0:12 | Title card: **serpapi_fdw** — "SerpApi as Postgres functions for Supabase and plain Postgres." One line under it: "Live search results become a table in the database you already have, and the wrapper meters its own credits." | Idea strength in one sentence |
| 0:12–0:30 | The finished thing first: `select * from public.strikethrough_forensics('2026-10-09') where inflated;` showing real iPhone rows: sale price, strikethrough, max seen over the prior nights, `inflated = true`. (Before Oct 9: show `price_changes` for the nights collected so far and say the forensics view is what runs on sale day.) | Usefulness; not LLM-answerable |
| 0:30–0:50 | Prove it is local and honest: `git clone … && supabase start` (pre-warmed, sped up), `scripts/build.sh` finishing in seconds, `scripts/load-local.sh` printing the server line, `.env.example` on screen (never a key). | Runs locally; no secrets |
| 0:50–1:20 | The core call, live: `select source, extracted_price, old_price from serpapi.google_shopping('iPhone 16');` Rows from Flipkart, Croma, Amazon.in appear; the right pane logs `google_shopping … rows=40 … 900ms`. Run it again: same rows, log shows the hit, `serpapi.budget_status()` unchanged (SerpApi cache). | Meaningful SerpApi usage; engine specificity (`gl=in`, location, Markdown-ready) |
| 1:20–1:40 | Named arguments and an explicit per-row call: `select p.query, s.asin, s.extracted_price from (values ('iPhone 16'),('iPhone 17')) p(query), lateral serpapi.amazon(p.query) s limit 6;` The log shows exactly two searches. Then `select * from serpapi.replay_amazon('<search_id>')` returning the same rows and the budget not moving: free re-read from SerpApi's archive. | Technical complexity; originality (functions, not a chat bot) |
| 1:40–2:00 | Guards, fast: `select * from serpapi.google_shopping(null)` → "q is required"; `alter server serpapi options (set hourly_cap '2')` then a third fresh query → "hourly cap reached (2/2) … resets at"; restore. A wrong-key error on screen with no URL in it. | CSE-grade robustness; key hygiene |
| 2:00–2:20 | The loop that produced the opening shot: `select * from cron.job;` (the nightly job), `select * from public.snapshot_runs order by id desc limit 5;` (one row per night, per-search commits, zero errors), `select captured_on, source, price, old_price from public.price_series where product_key = '<asin>' order by 1;` (the time series for one iPhone). | State over time; closed loop |
| 2:20–2:35 | Same functions through PostgREST: `curl -X POST …/rpc/google_shopping` with the anon key → policy error; with an authenticated JWT → rows and `budget_status` showing that user's daily quota. | Deterministic code decides; quotas per caller |
| 2:35–2:45 | The engines-and-roles table from the README on screen, then `scripts/smoke-assert.sh` printing `errors=5 warnings=0 … repeated_ok=6` and `cargo test` printing 27 passed (sped up). | Tests; honesty |
| 2:45–2:52 | End card: repo URL, track (Open-Source Integrations), "works on Supabase (hosted + local) and plain Postgres with the wrappers .deb", name, Bengaluru. | |

## What is deliberately not in the video

- No hosted Supabase footage (the rule says local; hosted is a README screenshot).
- No mock server (real data reads better; the mock is for tests and judges without a key).
- No architecture talk beyond one sentence; the README carries it.
- No Markdown-output or token-savings segment unless there is spare time at 2:35; it is a README number.

## Recording checklist

1. Night before: `scripts/dev-up.sh --no-mock`, `load-local.sh`, `apply-sql.sh`; confirm `smoke-assert.sh` passes against the mock first, then switch to live.
2. Within the hour before recording, run every query once (pre-warm; ~6 credits). Note one `search_id` and one ASIN for the replay and time-series shots.
3. Set the terminal to 120×34, font 16; hide the dock; close the Chrome tab with the dashboard (no keys on screen).
4. Record with QuickTime (screen only) or `ffmpeg`; speed the clone/build segment 4×.
5. Watch it back once for any string starting with `api_key=`; export; upload unlisted to YouTube; test in an incognito window.
6. Oct 9: re-record only 0:12–0:30 with the real forensics rows and re-export.
