#!/usr/bin/env python3
"""Record scripted browser scenes as 1920x1080 MP4 clips for demo/build.py.

  python3 demo/playground/record.py              # every scene
  python3 demo/playground/record.py p01-page     # one scene

Two surfaces: the static playground page (opened from file://, signs in through Supabase Auth,
calls PostgREST directly) and the local Supabase Studio SQL editor (http://127.0.0.1:54323).
Typing goes through the keyboard so the viewer sees it happen. Output: demo/out/browser/<scene>.mp4

Needs: demo/playground/config.js, demo/out/demo-user.env (DEMO_PASSWORD), the local stack with
auth + studio, and (for real data) the wrapper pointed at SerpApi rather than the mock.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

DEMO = Path(__file__).resolve().parent.parent
OUT = DEMO / "out" / "browser"
OUT.mkdir(parents=True, exist_ok=True)
PAGE_URL = "file://" + str((DEMO / "playground" / "index.html").resolve())
STUDIO_URL = "http://127.0.0.1:54323/project/default/sql/new"
W, H = 1920, 1080
STUDIO_ZOOM = os.environ.get("STUDIO_ZOOM", "1.4")
CREDS = dict(l.split("=", 1) for l in (DEMO / "out" / "demo-user.env").read_text().splitlines() if "=" in l)

# what the shots search for; swap SHOP to a live query when the wrapper is on real SerpApi
SHOP = os.environ.get("SHOP_QUERY", "iPhone 16")
NEWS = os.environ.get("NEWS_QUERY", "Bengaluru tech hiring")


# ---------------------------------------------------------------- helpers

def type_into(page: Page, selector: str, text: str, delay: int = 45):
    page.click(selector)
    page.fill(selector, "")
    page.keyboard.type(text, delay=delay)


def sign_in(page: Page):
    page.click("#who button[data-v=user]")
    page.wait_for_timeout(500)
    page.fill("#password", CREDS["DEMO_PASSWORD"])
    page.wait_for_timeout(400)
    page.click("#signin-go")
    page.wait_for_selector("#whois b", timeout=20000)


RELEASE = os.environ.get("RELEASE_TAG", "v0.1.0-rc1")
API_URL = os.environ.get("SERPAPI_API_URL", "")   # set to the mock URL for dry runs; empty = real SerpApi


def studio_prepare(page: Page, split_y: int = 0):
    """Collapse the query list and zoom the app so the grid reads at 1080p."""
    for sel in ["button:has-text('Collapse sidebar')", "button:has(svg.lucide-panel-left-close)", "button[aria-label*='ollapse']"]:
        if page.locator(sel).count():
            page.locator(sel).first.click()
            page.wait_for_timeout(300)
            break
    # editor/results split: drag the handle to SPLIT_Y (css px, before zoom); the split is kept as a percentage
    h = page.locator("[role=separator][aria-orientation=horizontal], [data-separator][aria-orientation=horizontal]").first
    if split_y and h.count():
        bb = h.bounding_box()
        if bb:
            page.mouse.move(bb["x"] + bb["width"] / 2, bb["y"])
            page.mouse.down()
            page.mouse.move(bb["x"] + bb["width"] / 2, split_y, steps=8)
            page.mouse.up()
            page.mouse.move(1900, 1070)
            page.wait_for_timeout(300)
    page.evaluate("""() => setInterval(() => document.querySelectorAll('header button, button').forEach(b => {
        if (/^(UPDATE AVAILABLE|LATEST)$/i.test(b.innerText.trim())) b.style.visibility = 'hidden'; }), 50)""")
    page.evaluate(f"document.documentElement.style.zoom='{STUDIO_ZOOM}'")
    # exact typing: no auto-closed brackets/quotes, no suggestion pop-ups
    page.evaluate("""() => monaco.editor.getEditors().forEach(e => e.updateOptions({autoClosingBrackets: 'never',
        autoClosingQuotes: 'never', autoIndent: 'none', autoSurround: 'never', quickSuggestions: false,
        suggestOnTriggerCharacters: false}))""")
    page.wait_for_timeout(500)


def studio_type(page: Page, lines: list[str], delay: int = 14):
    page.locator(".monaco-editor").first.click()
    page.keyboard.press("Meta+A")
    page.keyboard.press("Backspace")
    for i, line in enumerate(lines):
        page.keyboard.type(line, delay=delay)
        if i < len(lines) - 1:
            page.keyboard.press("Enter")


def studio_run(page: Page, timeout: int = 60000, wait_for: str = "[role=gridcell]"):
    page.wait_for_timeout(400)
    page.locator("button:has-text('Run')").first.click()   # the shortcut is unreliable in headless Chromium
    page.wait_for_selector(wait_for, timeout=timeout)


# ---------------------------------------------------------------- page scenes

def scene_p01_page(page: Page):
    """A file on disk asks Supabase: anonymous refused, signed in served, receipt replayed free."""
    page.wait_for_timeout(1200)
    type_into(page, "#q", SHOP)
    page.wait_for_timeout(400)
    page.click("#run")
    page.wait_for_selector("#body .state.err", timeout=30000)
    page.wait_for_timeout(4200)
    sign_in(page)
    page.wait_for_timeout(900)
    page.click("#run")
    page.wait_for_selector("#body table", timeout=60000)
    page.wait_for_timeout(6500)
    page.click("#replay")
    page.wait_for_timeout(6200)


def scene_p02_markdown(page: Page):
    """Markdown for agents, from the archive."""
    page.wait_for_timeout(600)
    sign_in(page)
    page.click("#engines button[data-v=google_news]")
    page.click("#mdtoggle")
    type_into(page, "#q", NEWS)
    page.wait_for_timeout(400)
    page.click("#run")
    page.wait_for_selector("#body .md", timeout=60000)
    page.wait_for_timeout(4000)


# ---------------------------------------------------------------- studio scenes

def scene_s01_install(page: Page):
    """Studio: create the server from the release URL (for real; the old server is dropped beforehand),
    import the foreign schema, then one select into Studio's grid."""
    import hashlib
    sha = hashlib.sha256((DEMO.parent / "dist" / "serpapi_fdw.wasm").read_bytes()).hexdigest()
    subprocess.run(["psql", os.environ.get("DB_URL_LOCAL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"),
                    "-q", "-c", "drop server if exists serpapi cascade;"], check=True, capture_output=True)
    page.wait_for_timeout(800)
    extra = [f"  api_url '{API_URL}',"] if API_URL else []
    studio_type(page, [
        "create server serpapi foreign data wrapper wasm_wrapper options (",
        f"  fdw_package_url 'https://github.com/krishna247/serpapi_fdw/releases/download/{RELEASE}/serpapi_fdw.wasm',",
        "  fdw_package_name 'serpapi:serpapi-fdw', fdw_package_version '0.1.0',",
        f"  fdw_package_checksum '{sha}',",
        "  api_key_name 'serpapi_api_key',",
        *extra,
        "  default_gl 'in', default_hl 'en', default_amazon_domain 'amazon.in');",
        "import foreign schema serpapi from server serpapi into serpapi_private;",
    ], delay=8)
    studio_run(page, timeout=120000, wait_for="text=/Success|No rows returned/")
    page.wait_for_timeout(2500)
    studio_type(page, [
        "select source, extracted_price as price, extracted_old_price as was, left(title, 70) as title",
        f"from serpapi.google_shopping('{SHOP}') order by position;",
    ])
    studio_run(page)
    page.wait_for_timeout(4500)


def scene_s02_ledger(page: Page):
    """Studio: the nightly ledger, the cron job, the receipt."""
    page.wait_for_timeout(1000)
    studio_type(page, [
        "select captured_on as night, product_key as asin, price, old_price as was",
        "from public.price_series where engine = 'amazon' order by asin, night;",
    ])
    studio_run(page)
    page.wait_for_timeout(3500)
    studio_type(page, ["select jobname, schedule, command from cron.job;"])
    studio_run(page)
    page.wait_for_timeout(3000)


def scene_s03_forensics(page: Page):
    """Studio: was the 'was' price ever real?"""
    page.wait_for_timeout(1000)
    studio_type(page, [
        "select product_key as asin, sale_price as price, strikethrough as was, max_seen_prior,",
        "       claimed_saving_pct as claimed, real_saving_pct as real, inflated, nights_observed as nights",
        "from public.strikethrough_forensics(current_date) where strikethrough is not null",
        "order by inflated desc, claimed desc;",
    ])
    studio_run(page)
    page.wait_for_timeout(5000)



# ---------------------------------------------------------------- v5 film shots (live SerpApi)
# Each scene does its setup off camera, then calls begin(page): the clip is trimmed to start there.

DB_LOCAL = os.environ.get("DB_URL_LOCAL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres")
_MARK: dict[str, float] = {}


def begin(page: Page):
    _MARK["t"] = time.monotonic()


def psql(sql: str) -> str:
    r = subprocess.run(["psql", DB_LOCAL, "-qAt", "-v", "ON_ERROR_STOP=1", "-c", sql],
                       check=True, capture_output=True, text=True)
    return r.stdout.strip()


SQL_DELAY = 35
INSTALL = [
    "create extension if not exists wrappers with schema extensions;",
    "create foreign data wrapper wasm_wrapper handler wasm_fdw_handler validator wasm_fdw_validator;",
    "",
    "select vault.create_secret('<your serpapi key>', 'serpapi_api_key');",
    "",
    "create server serpapi foreign data wrapper wasm_wrapper options (",
    "  fdw_package_url 'https://github.com/krishna247/serpapi_fdw/releases/download/v0.1.0/serpapi_fdw.wasm',",
    "  fdw_package_name 'serpapi:serpapi-fdw',",
    "  fdw_package_version '0.1.0',",
    "  fdw_package_checksum 'e91ef82b1cfd1c6bd045982c4848e76c0bc78eff57903c84d7d172181d84e54f',",
    "  api_key_name 'serpapi_api_key',",
    "  default_gl 'in', default_location 'Bengaluru,Karnataka,India', default_amazon_domain 'amazon.in',",
    "  hourly_cap '50', monthly_cap '250', max_pages '3'",
    ");",
]


def studio_paste(page: Page, lines: list[str]):
    """Put text in the editor at once (for 'already typed' shots)."""
    page.locator(".monaco-editor").first.click()
    page.keyboard.press("Meta+A")
    page.keyboard.press("Backspace")
    page.keyboard.insert_text("\n".join(lines))


def scene_r01_install(page: Page):
    """The README install block, run for real. The live server, wrapper and Vault secret are renamed aside
    first (restored straight after), so the block creates fresh objects and returns Success; the secret
    created on screen holds only the placeholder text."""
    psql("alter server serpapi rename to serpapi_live; "
         "alter foreign data wrapper wasm_wrapper rename to wasm_wrapper_live; "
         "select vault.update_secret(id, null, 'serpapi_api_key_live') from vault.secrets where name = 'serpapi_api_key';")
    try:
        studio_paste(page, INSTALL)
        page.keyboard.press("Meta+Home")
        page.wait_for_timeout(600)
        begin(page)
        page.wait_for_timeout(700)
        page.locator("button:has-text('Run')").first.click()   # once only: a second run would hit "already exists"
        # Studio shows the block's last result set: the id of the placeholder secret just created
        page.wait_for_selector("[role=gridcell]", timeout=15000)
        page.wait_for_timeout(1900)
    finally:
        psql("drop server if exists serpapi; drop foreign data wrapper if exists wasm_wrapper; "
             "delete from vault.secrets where name = 'serpapi_api_key'; "
             "alter foreign data wrapper wasm_wrapper_live rename to wasm_wrapper; "
             "alter server serpapi_live rename to serpapi; "
             "select vault.update_secret(id, null, 'serpapi_api_key') from vault.secrets where name = 'serpapi_api_key_live';")


def scene_r02_shopping(page: Page):
    begin(page)
    page.wait_for_timeout(300)
    studio_type(page, [f"select title, source, extracted_price from serpapi.google_shopping('{SHOP}');"], delay=SQL_DELAY)
    studio_run(page)
    page.wait_for_timeout(1700)


def scene_r08_cron(page: Page):
    """pg_cron schedules the nightly ledger (21:00 UTC = 02:30 IST); it is never due during the recording."""
    psql("select cron.unschedule(jobid) from cron.job where jobname = 'serpapi-nightly-prices';")
    # the line is already in the editor: the film match-cuts from the animation's collapsed SQL line
    studio_paste(page, ["select cron.schedule('serpapi-nightly-prices', '0 21 * * *',",
                        "  $$ call serpapi.snapshot_prices() $$);"])
    page.wait_for_timeout(400)
    begin(page)
    page.wait_for_timeout(600)
    studio_run(page)
    page.wait_for_timeout(700)
    studio_type(page, ["select jobname, schedule, command from cron.job;"], delay=25)
    studio_run(page, wait_for="[role=gridcell]:has-text('serpapi.snapshot_prices')")
    page.wait_for_timeout(1700)


def page_user(page: Page):
    """Sign in (demoPassword in config.js signs in silently) and wait for the user's quota."""
    page.click("#who button[data-v=user]")
    page.wait_for_selector("#m-user b", timeout=20000)


def page_search(page: Page, q: str, engine: str = "google_shopping", typed: bool = True):
    page.click(f"#engines button[data-v={engine}]")
    if typed:
        type_into(page, "#q", q, delay=70)
    else:
        page.fill("#q", q)
    page.wait_for_timeout(350)
    page.click("#run")


def wait_rows(page: Page):
    page.wait_for_function("() => document.querySelector('#body table') && !document.querySelector('#body.fading')",
                           timeout=60000)


def scene_r03_page_search(page: Page):
    page.wait_for_selector("#m-account:not(:has-text('–'))", timeout=20000)
    page_user(page)
    page.wait_for_timeout(500)
    begin(page)
    page.wait_for_timeout(900)
    page_search(page, SHOP)
    wait_rows(page)
    page.wait_for_timeout(6400)


def scene_r04_page_anon(page: Page):
    page.wait_for_selector("#m-account:not(:has-text('–'))", timeout=20000)
    page.fill("#q", SHOP)
    begin(page)
    page.wait_for_timeout(700)
    page.click("#who button[data-v=anon]")      # already anonymous: the page always opens that way
    page.wait_for_timeout(300)
    page.click("#run")
    page.wait_for_selector("#body .state.anon", timeout=20000)
    page.wait_for_timeout(2300)


def scene_r05_page_signed(page: Page):
    page.wait_for_selector("#m-account:not(:has-text('–'))", timeout=20000)
    page.fill("#q", SHOP)
    begin(page)
    page.wait_for_timeout(700)
    page_user(page)
    page.wait_for_timeout(700)
    page.click("#run")
    wait_rows(page)
    page.wait_for_timeout(3300)


def scene_r06_page_cap(page: Page):
    """Cap = what this hour has already used, so the next search is refused inside the wrapper."""
    page.wait_for_selector("#m-account:not(:has-text('–'))", timeout=20000)
    page_user(page)
    page.fill("#q", SHOP)
    used = psql("select used from serpapi.budget_status() where scope = 'account' and \"window\" = 'hour';")
    psql(f"alter server serpapi options (set hourly_cap '{max(int(used or 0), 1)}');")
    try:
        page.evaluate("refreshQuota()")
        page.wait_for_timeout(800)
        begin(page)
        page.wait_for_timeout(900)
        page.click("#run")
        page.wait_for_selector("#body .state.cap", timeout=30000)
        page.wait_for_timeout(3600)
    finally:
        psql("alter server serpapi options (set hourly_cap '50');")


def scene_r07_page_replay_md(page: Page):
    page.wait_for_selector("#m-account:not(:has-text('–'))", timeout=20000)
    page_user(page)
    page_search(page, os.environ.get("REPLAY_QUERY", SHOP), os.environ.get("REPLAY_ENGINE", "google_shopping"), typed=False)
    wait_rows(page)
    page.wait_for_timeout(1500)
    begin(page)
    page.wait_for_timeout(1300)
    page.click("#replay")
    page.wait_for_function("() => document.querySelector('#reqline').textContent.includes('archive')", timeout=30000)
    page.wait_for_timeout(2800)
    page.click("#mdtoggle")
    page.wait_for_selector("#body .md", timeout=30000)
    page.wait_for_timeout(3500)


SCENES = {
    "p01-page": (PAGE_URL, scene_p01_page),
    "p02-markdown": (PAGE_URL, scene_p02_markdown),
    "s01-install": (STUDIO_URL, scene_s01_install),
    "s02-ledger": (STUDIO_URL, scene_s02_ledger),
    "s03-forensics": (STUDIO_URL, scene_s03_forensics),
    "r01-install": (STUDIO_URL, scene_r01_install),
    "r02-shopping": (STUDIO_URL, scene_r02_shopping),
    "r03-page-search": (PAGE_URL, scene_r03_page_search),
    "r04-page-anon": (PAGE_URL, scene_r04_page_anon),
    "r05-page-signed": (PAGE_URL, scene_r05_page_signed),
    "r06-page-cap": (PAGE_URL, scene_r06_page_cap),
    "r07-page-replay-md": (PAGE_URL, scene_r07_page_replay_md),
    "r08-cron": (STUDIO_URL, scene_r08_cron),
}


SPLIT = {"r02-shopping": 300, "r08-cron": 300}   # css px for the editor/results handle (Studio clamps at 30%)


def record(name: str):
    url, fn = SCENES[name]
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": W, "height": H}, device_scale_factor=1, color_scheme="dark",
                            record_video_dir=str(OUT / "_raw"), record_video_size={"width": W, "height": H})
        page = ctx.new_page()
        t0 = time.monotonic()
        _MARK.clear()
        page.goto(url, wait_until="networkidle" if "54323" in url else "load", timeout=90000)
        if "54323" in url:
            page.wait_for_selector(".monaco-editor", timeout=60000)
            studio_prepare(page, SPLIT.get(name, 0))
        fn(page)
        video = page.video
        ctx.close()
        raw = Path(video.path()) if video else None
        b.close()
    if not raw or not raw.exists():
        sys.exit(f"no video for {name}")
    mp4 = OUT / f"{name}.mp4"
    trim = ["-ss", f"{_MARK['t'] - t0:.2f}"] if "t" in _MARK else []
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), *trim, "-r", "30", "-c:v", "libx264", "-preset", "medium",
                    "-crf", "18", "-pix_fmt", "yuv420p", "-an", str(mp4)], check=True)
    raw.unlink()
    print("wrote", mp4)


if __name__ == "__main__":
    for n in (sys.argv[1:] or list(SCENES)):
        record(n)
