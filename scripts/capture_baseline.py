#!/usr/bin/env python3
"""Fallback nightly capture for Strikethrough when the database cron cannot run (e.g. before the
hosted install exists). Mirrors public.tracked_searches: one Amazon.in search for "iPhone"
(2 pages) and one Google Shopping search for "iPhone 16", ~3 credits a night.

Raw SerpApi JSON is stored under fixtures/baseline/<YYYY-MM-DD>/ with search_ids (free replay for
31 days) and can be imported into public.price_snapshots later. Idempotent per day.

  scripts/capture_baseline.py --dry-run
  scripts/capture_baseline.py              # key from SERPAPI_API_KEY or ~/.serpapi_key
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "fixtures" / "baseline"
BASE = os.environ.get("SERPAPI_BASE", "https://serpapi.com")
LOCATION = "Bengaluru,Karnataka,India"

TRACKED = [
    {"name": "amazon-iphone-p1", "engine": "amazon", "k": "iPhone", "amazon_domain": "amazon.in", "page": "1",
     "json_restrictor": "search_metadata,search_parameters,error,serpapi_pagination,organic_results"},
    {"name": "amazon-iphone-p2", "engine": "amazon", "k": "iPhone", "amazon_domain": "amazon.in", "page": "2",
     "json_restrictor": "search_metadata,search_parameters,error,serpapi_pagination,organic_results"},
    {"name": "shopping-iphone-16", "engine": "google_shopping", "q": "iPhone 16", "gl": "in", "hl": "en",
     "location": LOCATION, "google_domain": "google.co.in",
     "json_restrictor": "search_metadata,search_parameters,error,serpapi_pagination,shopping_results"},
]


def api_key() -> str:
    k = os.environ.get("SERPAPI_API_KEY")
    key_file = Path.home() / ".serpapi_key"
    if not k and key_file.exists():
        k = key_file.read_text().strip()
    if not k:
        sys.exit("no key: set SERPAPI_API_KEY or write it to ~/.serpapi_key")
    return k


def fetch(params: dict[str, str], key: str) -> tuple[int, dict]:
    q = dict(sorted(params.items()))
    q["api_key"] = key
    url = f"{BASE}/search.json?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, headers={"user-agent": "serpapi_fdw-baseline/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"error": body[:200]}


def summarize(engine: str, data: dict) -> str:
    block = "shopping_results" if engine == "google_shopping" else "organic_results"
    rows = data.get(block) or []
    apple = [r for r in rows if str(r.get("title", "")).lower().startswith("apple iphone")]
    prices = [r.get("extracted_price") for r in apple if isinstance(r.get("extracted_price"), (int, float))]
    sid = (data.get("search_metadata") or {}).get("id", "?")
    if data.get("error"):
        return f"ERROR {data['error'][:70]}"
    return f"rows={len(rows):3d} iphones={len(apple):3d} min={min(prices) if prices else '-':>8} sid={sid}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-calls", type=int, default=6)
    ap.add_argument("--date", default=dt.date.today().isoformat())
    args = ap.parse_args()

    day_dir = OUT / args.date
    day_dir.mkdir(parents=True, exist_ok=True)
    key = "" if args.dry_run else api_key()
    calls = 0
    print(f"baseline {args.date}: {len(TRACKED)} searches -> {day_dir.relative_to(ROOT)}")
    for t in TRACKED:
        name = t["name"]
        params = {k: v for k, v in t.items() if k != "name"}
        out = day_dir / f"{name}.json"
        if out.exists():
            print(f"  {name:22} {summarize(t['engine'], json.loads(out.read_text()))}  (cached)")
            continue
        if args.dry_run:
            print(f"  {name:22} would fetch {params['engine']}")
            continue
        if calls >= args.max_calls:
            print(f"  stopping: --max-calls {args.max_calls} reached")
            return 2
        status, data = fetch(params, key)
        calls += 1
        if status != 200:
            print(f"  {name:22} HTTP {status}: {str(data.get('error'))[:80]}")
            if status in (401, 429):
                return 1
            continue
        out.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        print(f"  {name:22} {summarize(t['engine'], data)}")
        time.sleep(1.0)
    print(f"done: {calls} live searches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
