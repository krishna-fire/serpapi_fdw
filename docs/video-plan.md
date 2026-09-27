# The film (2:45)

A keynote, not a test report. One claim, one reveal, three pillars, a payoff, one more thing.
Every sentence is backed by a real terminal shot, because that is what the judges verify; the
cuts carry the argument. Constraints: under three minutes, running locally, no key on screen.

Voice: calm, short declaratives, pauses. Type: black cards, one idea per card, two to five words
in large type, a single line of small type beneath when needed. Terminal: one clean window, big
type, no prompt clutter, results that appear rather than scroll.

## Script

| Time | Card / screen | Voice |
|---|---|---|
| 0:00 | Black. Type fades in: **Every SerpApi tutorial ends the same way.** (beat) **Export to Sheets.** | — |
| 0:07 | **What if the results were already in your database?** | — |
| 0:12 | Terminal. One line types itself: `select source, price from serpapi.google_shopping('iPhone 16');` Rows appear: Flipkart, Croma, Amazon.in, Reliance… | "Google Shopping. As a Postgres function." |
| 0:22 | **serpapi_fdw** / *SerpApi, as SQL. For Supabase and Postgres.* | "This is serpapi_fdw." |
| 0:28 | **It's a table.** | "Three things." (beat) "First. It's a table." |
| 0:32 | `select asin, price, old_price from serpapi.amazon('iPhone', pages => 2);` → rows. Then a join: `from products p, lateral serpapi.amazon(p.query) s` → the log pane shows exactly two searches. | "Named arguments. Joins. Eight engines with typed columns, and a hundred more one call away." |
| 0:50 | `select * from serpapi.search('google_trends', '{"q":"air fryer","geo":"IN-KA"}');` → one JSON row. | "Any engine. Same rules." |
| 0:56 | **It keeps the receipts.** | "Second. It keeps the receipts." |
| 1:00 | Zoom on the `search_id` column. `select * from serpapi.replay_amazon('6ab9…');` → the same rows. `budget_status()` before and after: unchanged. | "Every row carries the search it came from. Read it again for thirty-one days. Free." |
| 1:14 | `select * from cron.job;` then `select * from snapshot_runs;` one row per night. Then one iPhone's `price_series`, nights stacked. | "Every night at two-thirty, it records the price of every iPhone on Amazon.in. Three credits." |
| 1:30 | **It never surprises your bill.** | "Third. It never surprises your bill." |
| 1:34 | `serpapi.budget_status()` → hour 7/50, month 41/250, user 3/20. Then a query that trips the cap: `serpapi: hourly cap reached (50/50), resets at 14:00`. Then a wrong-key error, zoomed: no URL in it. | "Caps live inside the wrapper. Quotas live per user. The key lives in Vault — and never in an error message." |
| 1:50 | `curl … /rpc/google_shopping` with the anon key → `anonymous callers are not allowed`; with a user token → rows. | "An app can call it. An anonymous visitor can't." |
| 1:58 | **October 9. Big Billion Days.** | — |
| 2:02 | `select * from strikethrough_forensics('2026-10-09') where inflated;` Zoom on one row: *was ₹149,900 → ₹119,900 · claimed 20% · real 4%*. | "The discount is a claim. The ledger is a fact." |
| 2:16 | **Under the hood.** Fast cuts: `cargo test` → 27 passed; `smoke-assert.sh` → errors=5 warnings=0; a 480 KB `.wasm`; `create server serpapi … fdw_package_url 'https://github.com/…/serpapi_fdw.wasm'`. Three logos in a row: Supabase hosted, Supabase local, Postgres. | "One wrapper, in Rust. Installs from a URL. Runs wherever Supabase Wrappers runs." |
| 2:32 | **One more thing.** | — |
| 2:35 | `select markdown from serpapi.search_md('google_news', '{"q":"Bengaluru tech hiring"}');` → a clean Markdown block. | "Markdown out. For your agents." |
| 2:42 | End card: **serpapi_fdw** · github.com/krishna-fire/serpapi_fdw · Open-Source Integrations · Krishna Janaswamy, Bengaluru | — |

Runtime of terminal footage: about 1:50 of 2:45. Cards never exceed six seconds.

## How it maps to the judging criteria (do not say this in the film)

Idea strength: 0:00–0:22. Originality: 0:28–0:56 (functions, joins, any engine), 2:35. Technical
complexity: 1:00–1:50, 2:16. Usefulness: 1:14, 1:58–2:16. Meaningful SerpApi usage: everything.

## Production

- **Terminal segments with VHS** (charmbracelet/vhs): a `.tape` file per segment, deterministic
  typing speed, waits, theme, 1920×1080, MP4 out. Repeatable, and it lives in the repo
  (`demo/tapes/`). Font 22, dark theme, prompt set to `❯`, no window chrome.
- **Cards in Keynote**: black background, SF Pro Display, white type, one idea per card, a
  slow fade in and a hard cut out. Export at 1080p.
- **Assembly in iMovie or Final Cut**: cards and tapes alternate; cross-dissolve only between
  a card and its terminal shot; no transitions inside terminal footage. Zooms are done in the
  editor (Ken Burns on the row that matters), not by scrolling the terminal.
- **Voice**: Krishna's own voice, recorded separately with the script above, then aligned.
  Short sentences. Leave air after each card.
- **Music**: none, or one quiet royalty-free bed under the cards only. Silence under terminal.
- **Data**: real SerpApi, local stack (`scripts/dev-up.sh --no-mock`), pre-warmed within the
  hour so every take hits SerpApi's cache. About six fresh searches on the day, approved first.
- **Before Oct 9**: 1:58–2:16 uses the nights collected so far with `price_series`; re-shoot only
  that segment on Oct 9 and re-export. Everything else is final by Oct 3.
- **Check before upload**: play once looking for any string beginning `api_key=`; unlisted
  YouTube; open the link in an incognito window; confirm under 3:00.

## VHS tape skeleton (demo/tapes/01-reveal.tape)

```
Output demo/out/01-reveal.mp4
Set FontSize 22
Set Width 1920
Set Height 1080
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms
Set Padding 40
Hide
Type "psql \"$DB_URL\" -q" Enter
Sleep 1s
Show
Type "select source, extracted_price as price from serpapi.google_shopping('iPhone 16') order by price limit 8;"
Sleep 800ms
Enter
Sleep 4s
```
