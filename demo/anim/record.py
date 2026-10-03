#!/usr/bin/env python3
"""Render the animated scenes (demo/anim/<id>.html) to 1920x1080 30 fps H.264 clips.

  python3 demo/anim/record.py            # every scene
  python3 demo/anim/record.py a05-request-path a06-catalog

Frame-exact capture with a virtual clock: each page is opened with ?capture (timeline paused at 0),
then for every frame record.py calls window.__seek(t) and grabs a screenshot, piping PNGs into ffmpeg.
No wall-clock timing, so no dropped frames and no blank lead-in to trim. Length = DURATION + 0.5 s
(DURATION is the constant at the top of each page; the last frame holds). Output: demo/out/anim/<id>.mp4
"""
from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEMO = HERE.parent
VENV_PY = DEMO / ".venv-tts" / "bin" / "python"

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # same interpreter demo/playground/record.py runs under
    if VENV_PY.exists() and Path(sys.executable).resolve() != VENV_PY.resolve():
        os.execv(str(VENV_PY), [str(VENV_PY), __file__, *sys.argv[1:]])
    sys.exit("playwright not installed (pip install playwright && playwright install chromium)")

OUT = DEMO / "out" / "anim"
W, H, FPS, TAIL = 1920, 1080, 30, 0.5


def scenes() -> list[Path]:
    return sorted(p for p in HERE.glob("a[0-9][0-9]-*.html"))


def duration_of(page: Path) -> float:
    m = re.search(r"const\s+DURATION\s*=\s*([\d.]+)", page.read_text())
    if not m:
        raise SystemExit(f"{page.name}: no `const DURATION = …` at the top")
    return float(m.group(1))


def render(page_path: str) -> str:
    page_file = Path(page_path)
    sid = page_file.stem
    secs = duration_of(page_file) + TAIL
    frames = round(secs * FPS)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{sid}.mp4"
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "png", "-i", "-",
         "-c:v", "libx264", "-preset", "slow", "-crf", "14", "-tune", "animation", "-pix_fmt", "yuv420p",
         "-r", str(FPS), "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE)
    assert ff.stdin is not None
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--force-color-profile=srgb", "--hide-scrollbars", "--font-render-hinting=none"])
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1)
        page = ctx.new_page()
        page.goto(page_file.as_uri() + "?capture")
        page.wait_for_function("window.__ready === true", timeout=15000)
        cdp = ctx.new_cdp_session(page)
        for i in range(frames):
            page.evaluate("t => window.__seek(t)", i / FPS)
            shot = cdp.send("Page.captureScreenshot", {"format": "png", "optimizeForSpeed": True})
            ff.stdin.write(base64.b64decode(shot["data"]))
        browser.close()
    ff.stdin.close()
    if ff.wait() != 0:
        raise SystemExit(f"ffmpeg failed for {sid}")
    return f"{sid}  {secs:.1f}s  {frames} frames -> {out.relative_to(DEMO.parent)}"


def main(argv: list[str]) -> int:
    pages = scenes()
    if argv:
        want = set(argv)
        pages = [p for p in pages if p.stem in want or p.stem.split("-")[0] in want]
        missing = want - {p.stem for p in pages} - {p.stem.split("-")[0] for p in pages}
        if missing:
            sys.exit(f"unknown scene(s): {', '.join(sorted(missing))}")
    workers = min(len(pages), max(1, (os.cpu_count() or 4) // 2))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for line in pool.map(render, [str(p) for p in pages]):
            print(line, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
