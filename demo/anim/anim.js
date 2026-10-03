/* serpapi_fdw film: tiny deterministic timeline for demo/anim/*.html.
 *
 * A page sets `const DURATION = <seconds>` and may define `function frame(t)` (t in seconds).
 * All CSS animations plus frame(t) are driven from one clock:
 *   - normal open: plays in real time from load, then holds the last frame;
 *   - ?capture   : paused at 0, sets window.__ready; record.py calls window.__seek(t) per frame;
 *   - ?t=4.2     : frozen at 4.2 s (for checking a still).
 * The chapter bar is built from <nav class="chapters" data-chapter="2" data-from=".2" data-to=".6">.
 */
(function () {
  const CHAPTERS = ["The key", "Under the hood", "Your app", "Batteries included", "Schedules", "Anywhere"];

  // ---- easing (cubic-bezier solver) -------------------------------------------------------
  function bezier(x1, y1, x2, y2) {
    const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
    const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
    const sx = t => ((ax * t + bx) * t + cx) * t, sy = t => ((ay * t + by) * t + cy) * t;
    const dx = t => (3 * ax * t + 2 * bx) * t + cx;
    return x => {
      if (x <= 0) return 0; if (x >= 1) return 1;
      let t = x;
      for (let i = 0; i < 8; i++) { const e = sx(t) - x, d = dx(t); if (Math.abs(e) < 1e-6 || Math.abs(d) < 1e-6) break; t -= e / d; }
      let lo = 0, hi = 1; if (Math.abs(sx(t) - x) > 1e-5) { t = x; for (let i = 0; i < 30; i++) { const v = sx(t); if (v < x) lo = t; else hi = t; t = (lo + hi) / 2; } }
      return sy(t);
    };
  }
  const E = {
    out: bezier(.22, 1, .36, 1),
    io: bezier(.65, 0, .35, 1),
    soft: bezier(.45, 0, .2, 1),
    back: bezier(.34, 1.4, .64, 1),
    in: bezier(.55, 0, 1, .45),
    lin: x => Math.max(0, Math.min(1, x)),
  };
  const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
  /** eased progress of a segment starting at `start` lasting `dur` seconds */
  const p = (t, start, dur, ease = "out") => E[ease](clamp((t - start) / dur));
  const lerp = (a, b, k) => a + (b - a) * k;

  function typeText(el, text, t, start, cps = 28, caret = true) {
    const n = Math.floor(clamp((t - start) * cps, 0, text.length));
    const done = n >= text.length;
    const blinkOn = Math.floor(t * 2.2) % 2 === 0;
    el.textContent = text.slice(0, n);
    if (caret && t >= start - 0.4) {
      const c = document.createElement("span");
      c.className = "caret";
      c.style.opacity = done ? (blinkOn ? 1 : 0) : 1;
      el.appendChild(c);
    }
  }

  // ---- chapter bar ------------------------------------------------------------------------
  function buildChapters() {
    const nav = document.querySelector("nav.chapters");
    if (!nav) return null;
    const cur = +nav.dataset.chapter;
    nav.innerHTML = CHAPTERS.map((name, i) => {
      const n = i + 1, cls = n < cur ? "past" : n === cur ? "now" : "";
      return `<div class="chapter ${cls}"><div class="label"><span class="num">0${n}</span><span class="name">${name}</span></div><div class="track"><div class="fill"></div></div></div>`;
    }).join("");
    const fill = nav.querySelector(".chapter.now .fill");
    const from = +(nav.dataset.from || 0), to = +(nav.dataset.to || 1);
    return t => { if (fill) fill.style.width = (lerp(from, to, clamp(t / window.__duration)) * 100).toFixed(2) + "%"; };
  }

  // ---- clock ------------------------------------------------------------------------------
  let chapterTick = null;
  function seek(t) {
    const ms = t * 1000;
    for (const a of document.getAnimations()) { a.pause(); a.currentTime = ms; }
    if (chapterTick) chapterTick(t);
    if (typeof window.frame === "function") window.frame(t);
  }

  window.A = { E, p, clamp, lerp, typeText, bezier };
  window.__seek = seek;

  async function start() {
    window.__duration = typeof DURATION === "number" ? DURATION : 5;
    chapterTick = buildChapters();
    if (typeof window.setup === "function") window.setup();
    try { await document.fonts.ready; } catch (e) {}
    const q = new URLSearchParams(location.search);
    if (q.has("capture")) { seek(0); window.__ready = true; return; }
    if (q.has("t")) { seek(+q.get("t")); window.__ready = true; return; }
    const t0 = performance.now();
    const loop = now => {
      const t = Math.min((now - t0) / 1000, window.__duration + 0.5);
      seek(t);
      requestAnimationFrame(loop);
    };
    seek(0);
    requestAnimationFrame(loop);
    window.__ready = true;
  }
  if (document.readyState === "complete") start(); else window.addEventListener("load", start);
})();
