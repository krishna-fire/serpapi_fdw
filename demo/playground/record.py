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

import subprocess
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

DEMO = Path(__file__).resolve().parent.parent
OUT = DEMO / "out" / "browser"
OUT.mkdir(parents=True, exist_ok=True)
PAGE_URL = "file://" + str((DEMO / "playground" / "index.html").resolve())
STUDIO_URL = "http://127.0.0.1:54323/project/default/sql/new"
W, H = 1920, 1080
CREDS = dict(l.split("=", 1) for l in (DEMO / "out" / "demo-user.env").read_text().splitlines() if "=" in l)

# what the shots search for; swap SHOP to a live query when the wrapper is on real SerpApi
import os
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


def studio_prepare(page: Page):
    """Collapse the query list and zoom the app so the grid reads at 1080p."""
    for sel in ["button:has(svg.lucide-panel-left-close)", "button[aria-label*='ollapse']"]:
        if page.locator(sel).count():
            page.locator(sel).first.click()
            page.wait_for_timeout(300)
            break
    page.evaluate("document.documentElement.style.zoom='1.3'")
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
    page.wait_for_timeout(500)
    page.keyboard.press("Meta+Enter")          # Studio's run shortcut (editor has focus after typing)
    try:
        page.wait_for_selector(wait_for, timeout=8000)
    except Exception:
        page.locator("button:has-text('Run')").first.click(timeout=10000)
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


SCENES = {
    "p01-page": (PAGE_URL, scene_p01_page),
    "p02-markdown": (PAGE_URL, scene_p02_markdown),
    "s01-install": (STUDIO_URL, scene_s01_install),
    "s02-ledger": (STUDIO_URL, scene_s02_ledger),
    "s03-forensics": (STUDIO_URL, scene_s03_forensics),
}


def record(name: str):
    url, fn = SCENES[name]
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": W, "height": H}, device_scale_factor=1, color_scheme="dark",
                            record_video_dir=str(OUT / "_raw"), record_video_size={"width": W, "height": H})
        page = ctx.new_page()
        page.goto(url, wait_until="networkidle" if "54323" in url else "load", timeout=90000)
        if "54323" in url:
            page.wait_for_selector(".monaco-editor", timeout=60000)
            studio_prepare(page)
        fn(page)
        video = page.video
        ctx.close()
        raw = Path(video.path()) if video else None
        b.close()
    if not raw or not raw.exists():
        sys.exit(f"no video for {name}")
    mp4 = OUT / f"{name}.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-r", "30", "-c:v", "libx264", "-preset", "medium",
                    "-crf", "18", "-pix_fmt", "yuv420p", "-an", str(mp4)], check=True)
    raw.unlink()
    print("wrote", mp4)


if __name__ == "__main__":
    for n in (sys.argv[1:] or list(SCENES)):
        record(n)
