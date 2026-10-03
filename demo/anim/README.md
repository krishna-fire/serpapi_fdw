# Animated scenes (ANIM beats of video/script-v5.md)
Each `aNN-*.html` is a 1920x1080 page on a deterministic timeline (`anim.js`, shared look in `style.css`); `const DURATION` at the top = voice + 0.8 s, after which it holds. Open a page to preview (`?t=4.2` freezes a frame).
Render: `python3 demo/anim/record.py [id ...]` (frame-exact capture via Playwright in demo/.venv-tts, ffmpeg H.264 30 fps yuv420p) → `demo/out/anim/<id>.mp4`, length DURATION + 0.5 s.
a01-key-app 6.6s (0:00 app assembles) · a02-key-search 8.1s (0:07 search + key in browser) · a03-key-vault 3.6s (0:14 key into Vault) · a04-title 5.0s (0:17 title)
a05-request-path 13.5s (0:27 request path) · a06-catalog 9.9s (0:40 one catalog, 8+1 engines) · a07-code-rpc 4.5s (0:50 CODE card)
a08-batteries 3.9s (1:08 five cells) · a09-caps-gauge 4.2s (1:23 ANIM half: caps inside the wrapper) · a10-cache 6.3s (1:32 canonical URL → cache)
a11-cron-collapse 9.9s (1:45 usual way → one pg_cron line) · a12-ledger-clock 9.1s (2:03 illustration: nightly ledger)
a13-anywhere 9.4s (2:12 one .wasm, three slots, install line) · a14-apps 6.5s (2:28 slots feed apps)
a15-stats 9.9s (2:36 tagline + count-ups) · a16-endcard 5.0s (2:43 end card, no voice; fade to black left to the builder)
