#!/usr/bin/env python3
"""Nightly baseline capture for Strikethrough, usable before the wrapper exists.

Fetches Google Shopping (gl=in) and Amazon.in results for every product in
fixtures/baseline/products.json and stores the raw SerpApi JSON under
fixtures/baseline/<YYYY-MM-DD>/<sku>.<engine>.json  (search_id included -> free replay for 31 days).

Costs 2 credits per product per day (20 for the default list). Idempotent: existing files
for today are skipped, so re-running costs nothing.

  SERPAPI_API_KEY=... scripts/capture_baseline.py          # or key in ~/.serpapi_key
  scripts/capture_baseline.py --dry-run                     # show what would be fetched
  scripts/capture_baseline.py --max-calls 6                 # hard budget guard
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
PRODUCTS = ROOT / "fixtures" / "baseline" / "products.json"
OUT = ROOT / "fixtures" / "baseline"
BASE = os.environ.get("SERPAPI_BASE", "https://serpapi.com")

LOCATION = "Bengaluru,Karnataka,India"


def api_key() -> str:
    k = os.environ.get("SERPAPI_API_KEY")
    key_file = Path.home() / ".serpapi_key"
    if not k and key_file.exists():
        k = key_file.read_text().strip()
    if not k:
        sys.exit("no key: set SERPAPI_API_KEY or write it to ~/.serpapi_key")
    return k


def engines_for(query: str) -> dict[str, dict[str, str]]:
    return {
        "google_shopping": {
            "engine": "google_shopping",
            "q": query,
            "gl": "in",
            "hl": "en",
            "location": LOCATION,
            "google_domain": "google.co.in",
            "json_restrictor": "search_metadata,search_parameters,error,serpapi_pagination,shopping_results",
        },
        "amazon": {
            "engine": "amazon",
            "k": query,
            "amazon_domain": "amazon.in",
            "json_restrictor": "search_metadata,search_parameters,error,serpapi_pagination,organic_results",
        },
    }


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
    prices = [r.get("extracted_price") for r in rows if isinstance(r.get("extracted_price"), (int, float))]
    sources = sorted({r.get("source") for r in rows if r.get("source")})[:6] if engine == "google_shopping" else []
    sid = (data.get("search_metadata") or {}).get("id", "?")
    err = data.get("error")
    if err:
        return f"{engine:16} ERROR {err[:70]}"
    return f"{engine:16} rows={len(rows):3d} min={min(prices) if prices else '-':>8} sid={sid} {' '.join(sources)}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-calls", type=int, default=40, help="hard guard on live searches this run")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    args = ap.parse_args()

    products = json.loads(PRODUCTS.read_text())
    day_dir = OUT / args.date
    day_dir.mkdir(parents=True, exist_ok=True)
    key = "" if args.dry_run else api_key()
    calls = 0

    print(f"baseline {args.date}: {len(products)} products x 2 engines -> {day_dir.relative_to(ROOT)}")
    for p in products:
        for engine, params in engines_for(p["query"]).items():
            out = day_dir / f"{p['sku']}.{engine}.json"
            if out.exists():
                data = json.loads(out.read_text())
                print(f"  {p['sku']:22} {summarize(engine, data)}  (cached)")
                continue
            if args.dry_run:
                print(f"  {p['sku']:22} {engine:16} would fetch")
                continue
            if calls >= args.max_calls:
                print(f"  stopping: --max-calls {args.max_calls} reached")
                return 2
            status, data = fetch(params, key)
            calls += 1
            if status != 200:
                print(f"  {p['sku']:22} {engine:16} HTTP {status}: {str(data.get('error'))[:80]}")
                if status in (401, 429):
                    return 1
                continue
            out.write_text(json.dumps(data, ensure_ascii=False, indent=1))
            print(f"  {p['sku']:22} {summarize(engine, data)}")
            time.sleep(1.0)  # stay well under 50/hour and be polite
    print(f"done: {calls} live searches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
