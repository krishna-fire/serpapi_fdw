#!/usr/bin/env python3
"""Render every card in demo/film.json to a 1920x1080 PNG with headless Chrome."""
from __future__ import annotations

import html
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEMO = HERE.parent
FILM = json.loads((DEMO / "film.json").read_text())
OUT = DEMO / "out" / "cards"
OUT.mkdir(parents=True, exist_ok=True)

CHROME = next(
    (p for p in [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chrome"),
    ] if p and Path(p).exists()),
    None,
)
if not CHROME:
    sys.exit("no Chrome/Chromium found for headless rendering")
CHROME_BIN: str = CHROME

TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:#000;width:{w}px;height:{h}px;overflow:hidden}
.c{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;
   color:#fff;font-family:-apple-system,"SF Pro Display","Helvetica Neue",Inter,sans-serif;text-align:center;padding:0 160px}
h1{font-size:{size}px;font-weight:600;letter-spacing:-0.025em;margin:0;line-height:1.06}
h1.mono{font-family:"SF Mono",ui-monospace,Menlo,monospace;font-weight:500;letter-spacing:-0.01em}
p{font-size:34px;font-weight:400;color:#8e8e93;margin:30px 0 0;letter-spacing:0.005em}
</style></head><body><div class="c"><h1 class="{cls}">{title}</h1>{sub}</div></body></html>"""


def render(seg: dict) -> Path:
    title = seg["title"]
    words = len(title.split())
    size = 104 if words <= 3 else 92 if words <= 6 else 72
    mono = title.replace(".", "").replace("_", "").isalnum() and "_" in title  # serpapi_fdw
    sub = f"<p>{html.escape(seg['subtitle'])}</p>" if seg.get("subtitle") else ""
    page = (TEMPLATE.replace("{w}", str(FILM["width"])).replace("{h}", str(FILM["height"]))
            .replace("{size}", str(size)).replace("{cls}", "mono" if mono else "")
            .replace("{title}", html.escape(title)).replace("{sub}", sub))
    src = OUT / f"{seg['id']}.html"
    png = OUT / f"{seg['id']}.png"
    src.write_text(page)
    subprocess.run([CHROME_BIN, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    f"--window-size={FILM['width']},{FILM['height']}", f"--screenshot={png}", f"file://{src}"],
                   check=True, capture_output=True)
    return png


def main() -> int:
    for seg in FILM["segments"]:
        if seg["type"] == "card":
            print("card", seg["id"], "->", render(seg).name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
