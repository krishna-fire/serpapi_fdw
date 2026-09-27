#!/usr/bin/env python3
"""Tiny SerpApi look-alike that serves recorded fixtures, for SQL smoke tests and offline demos.

  python3 mock/server.py --port 8787 --fixtures fixtures/serp
Then point the foreign server at it:
  api_url 'http://host.docker.internal:8787'   (from inside the supabase db container)

Routing:
  GET /search.json?engine=E&q=Q&...   -> fixtures/serp/<E>/<slug(Q or k or data_id)>.json, else generic <E>/default.json
  GET /searches/<id>.json              -> the fixture whose search_metadata.id == <id> (indexed at start)
  GET /searches/<id>.md                -> fixtures/serp/_md/<id>.md if present, else a rendering of the JSON
  GET /account.json                    -> fixtures/serp/account.json
Any request without api_key -> 401 with SerpApi's error shape. Unknown -> 200 with the "no results" error.
"""
from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIX = Path("fixtures/serp")
BY_ID: dict[str, Path] = {}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:80]


def index_ids() -> None:
    for p in FIX.rglob("*.json"):
        try:
            sid = json.loads(p.read_text()).get("search_metadata", {}).get("id")
            if sid:
                BY_ID[sid] = p
        except Exception:
            pass


class H(BaseHTTPRequestHandler):
    def _send(self, code: int, body: str, ctype: str = "application/json") -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 — quieter, and never logs api_key
        _ = (format, args)
        print("mock:", self.path.split("api_key=")[0][:120])

    def do_GET(self) -> None:
        u = urlparse(self.path)
        qs = {k: v[0] for k, v in parse_qs(u.query).items()}
        if "api_key" not in qs or not qs["api_key"]:
            return self._send(401, json.dumps({"error": "Invalid API key. Your API key should be here: https://serpapi.com/manage-api-key"}))

        if u.path == "/account.json":
            p = FIX / "account.json"
            return self._send(200, p.read_text() if p.exists() else json.dumps({"account_email": "mock@example.com", "plan_name": "Free", "plan_searches_left": 213, "this_hour_searches": 3, "account_rate_limit_per_hour": 50}))

        m = re.match(r"^/searches/([^/]+)\.(json|md)$", u.path)
        if m:
            sid, ext = m.groups()
            if ext == "md":
                md = FIX / "_md" / f"{sid}.md"
                if md.exists():
                    return self._send(200, md.read_text(), "text/markdown")
                p = BY_ID.get(sid)
                return self._send(200, f"# search {sid}\n\n```json\n{p.read_text()[:2000] if p else '{}'}\n```\n", "text/markdown") if p else self._send(404, json.dumps({"error": "not found"}))
            p = BY_ID.get(sid)
            return self._send(200, p.read_text()) if p else self._send(404, json.dumps({"error": "Search not found"}))

        if u.path == "/search.json":
            engine = qs.get("engine", "google")
            key = qs.get("q") or qs.get("k") or qs.get("data_id") or qs.get("place_id") or "default"
            cands = [FIX / engine / f"{slug(key)}.json", FIX / engine / "default.json"]
            for p in cands:
                if p.exists():
                    return self._send(200, p.read_text())
            return self._send(200, json.dumps({
                "search_metadata": {"id": f"mock-{slug(engine)}-{slug(key)}", "status": "Success"},
                "search_parameters": {k: v for k, v in qs.items() if k != "api_key"},
                "error": "Google hasn't returned any results for this query.",
            }))

        self._send(404, json.dumps({"error": "unknown path"}))


def main() -> None:
    global FIX
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--fixtures", default=str(FIX))
    a = ap.parse_args()
    FIX = Path(a.fixtures)
    index_ids()
    print(f"mock serpapi on :{a.port}, {len(BY_ID)} fixtures indexed from {FIX}")
    ThreadingHTTPServer(("0.0.0.0", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
