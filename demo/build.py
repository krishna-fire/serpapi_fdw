#!/usr/bin/env python3
"""Assemble the film: cards (PNG → clips with fades), tapes (VHS in Docker), narration (local Kokoro TTS
or macOS `say`), then one 1080p MP4 plus a timeline.

  DB_URL=postgresql://postgres:postgres@host.docker.internal:54322/postgres python3 demo/build.py
  python3 demo/build.py --skip-tapes      # re-assemble without re-rendering terminal shots
  python3 demo/build.py --only t01-reveal # render one tape
  python3 demo/build.py --skip-tapes --no-voice   # silent cut, for a human voice-over

Segment types in film.json: card (HTML → PNG → clip), tape (VHS terminal, demo/tapes/<id>.tape),
browser (Playwright scene in demo/playground/record.py), anim (animated scene, demo/anim/<id>.html).

Narration: film.json "voice_engine" kokoro (local Kokoro-82M via mlx-audio in demo/.venv-tts), chirp (Google
Chirp 3 HD; API key in ~/.google-tts-key), elevenlabs (API key in ~/.elevenlabs_key; "voice" is a voice id,
"voice_model" defaults to eleven_multilingual_v2) or say (macOS); "voice" (kokoro: af_heart, bf_emma ...; chirp:
en-IN-Chirp3-HD-Algenib ...), "voice_speed". Audition: build.py --engine chirp --audition "line" --voices a,b
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEMO = Path(__file__).resolve().parent
ROOT = DEMO.parent
FILM = json.loads((DEMO / "film.json").read_text())
OUT = DEMO / "out"
TAPES_OUT = OUT / "tapes"
BROWSER_OUT = OUT / "browser"
ANIM_OUT = OUT / "anim"
CLIPS = OUT / "clips"
AUDIO = OUT / "audio"
for d in (TAPES_OUT, BROWSER_OUT, ANIM_OUT, CLIPS, AUDIO):
    d.mkdir(parents=True, exist_ok=True)

W, H, FPS = FILM["width"], FILM["height"], FILM["fps"]
FADE = FILM.get("card_fade", 0.6)
VOICE = FILM.get("voice", "af_heart")


def sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kw)


def duration(path: Path) -> float:
    r = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(r.stdout.strip())


# ---------------------------------------------------------------- tapes (VHS in Docker)

def render_tape(tape_id: str) -> Path:
    tape = DEMO / "tapes" / f"{tape_id}.tape"
    env = {k: v for k, v in os.environ.items() if k in ("DB_URL", "ANON_JWT", "USER_JWT")}
    if "DB_URL" not in env:
        sys.exit("set DB_URL (use host.docker.internal for a local database)")
    jwts = OUT / "jwts.env"
    if jwts.exists():
        for line in jwts.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                env.setdefault(k, v)
    cmd = ["docker", "run", "--rm", "--add-host=host.docker.internal:host-gateway",
           "-v", f"{ROOT}:/vhs", "-w", "/vhs"]
    for k, v in env.items():
        cmd += ["-e", f"{k}={v}"]
    cmd += ["serpapi-fdw-vhs:latest", str(tape.relative_to(ROOT))]
    print(f"  rendering {tape_id} …", flush=True)
    subprocess.run(cmd, check=True)
    out = TAPES_OUT / f"{tape_id}.mp4"
    if not out.exists():
        sys.exit(f"tape did not produce {out}")
    return out


# ---------------------------------------------------------------- browser scenes (Playwright)

def render_browser(scene_id: str) -> Path:
    """Drive the playground page with demo/playground/record.py (needs the page server on :8790)."""
    py = DEMO / ".venv-tts" / "bin" / "python"
    env = dict(os.environ, VIRTUAL_ENV=str(py.parent.parent), PATH=f"{py.parent}:{os.environ['PATH']}")
    print(f"  recording {scene_id} …", flush=True)
    subprocess.run([str(py), str(DEMO / "playground" / "record.py"), scene_id], check=True, env=env)
    out = BROWSER_OUT / f"{scene_id}.mp4"
    if not out.exists():
        sys.exit(f"scene did not produce {out}")
    return out


def render_anim(scene_id: str) -> Path:
    """Record one animated scene (demo/anim/<id>.html) with demo/anim/record.py."""
    py = DEMO / ".venv-tts" / "bin" / "python"
    print(f"  animating {scene_id} …", flush=True)
    subprocess.run([str(py), str(DEMO / "anim" / "record.py"), scene_id], check=True)
    out = ANIM_OUT / f"{scene_id}.mp4"
    if not out.exists():
        sys.exit(f"scene did not produce {out}")
    return out


def source(seg: dict) -> Path:
    """The recorded clip behind a non-card segment."""
    base = {"browser": BROWSER_OUT, "anim": ANIM_OUT}.get(seg["type"], TAPES_OUT)
    return base / f"{seg['id']}.mp4"


RENDER = {"tape": render_tape, "browser": render_browser, "anim": render_anim}


# ---------------------------------------------------------------- cards → clips

VO_PAD = FILM.get("vo_pad", 0.9)   # seconds of air after a narration line ends


def card_clip(seg: dict, min_secs: float = 0.0) -> Path:
    png = OUT / "cards" / f"{seg['id']}.png"
    clip = CLIPS / f"{seg['id']}.mp4"
    secs = max(float(seg["seconds"]), min_secs)
    fade_out = max(secs - FADE, 0)
    sh(["ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS), "-i", str(png), "-t", f"{secs}",
        "-vf", f"fade=t=in:st=0:d={FADE},fade=t=out:st={fade_out}:d={FADE},format=yuv420p",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", str(FPS), str(clip)])
    return clip


def tape_clip(seg: dict, min_secs: float = 0.0) -> Path:
    src = source(seg)
    clip = CLIPS / f"{seg['id']}.mp4"
    # normalise every recording to the film's size/fps, hold the last frame if the narration runs longer,
    # and add a short fade in/out so cuts breathe
    d = duration(src)
    hold = max(min_secs - d, 0.0)
    total = d + hold
    pad = f"tpad=stop_mode=clone:stop_duration={hold:.2f}," if hold > 0 else ""
    # "fade": false for match cuts and animations that carry their own transition
    fade = (f"fade=t=in:st=0:d=0.35,fade=t=out:st={max(total-0.35,0)}:d=0.35,"
            if seg.get("fade", seg["type"] != "anim") else "")
    sh(["ffmpeg", "-y", "-i", str(src), "-vf",
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=#0b0b0d,{pad}"
        f"{fade}format=yuv420p",
        "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-an", str(clip)])
    return clip


# ---------------------------------------------------------------- narration

ENGINE = FILM.get("voice_engine", "kokoro")          # kokoro (local), chirp (Google Chirp 3 HD), elevenlabs, say (macOS)
SPEED = FILM.get("voice_speed", 0.9)
TTS_PY = DEMO / ".venv-tts" / "bin" / "python"
CHIRP_KEY_FILE = Path(os.environ.get("GOOGLE_TTS_KEY_FILE", Path.home() / ".google-tts-key"))
ELEVEN_KEY_FILE = Path(os.environ.get("ELEVENLABS_KEY_FILE", Path.home() / ".elevenlabs_key"))
ELEVEN_MODEL = os.environ.get("ELEVEN_MODEL") or FILM.get("voice_model", "eleven_multilingual_v2")


def chirp(text: str, voice: str, speed: float, out: Path) -> None:
    """Google Cloud Text-to-Speech, Chirp 3 HD. Voice ids look like en-IN-Chirp3-HD-Algenib.
    The API key is read from ~/.google-tts-key (never printed); free tier is 1M characters/month."""
    key = CHIRP_KEY_FILE.read_text().strip()
    lang = "-".join(voice.split("-")[:2])
    inp = {"markup": text} if "[pause" in text else {"text": text}
    body = {"input": inp, "voice": {"languageCode": lang, "name": voice},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 24000, "speakingRate": speed}}
    req = urllib.request.Request("https://texttospeech.googleapis.com/v1/text:synthesize", data=json.dumps(body).encode(),
                                 headers={"X-goog-api-key": key, "Content-Type": "application/json; charset=utf-8"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            out.write_bytes(base64.b64decode(json.load(r)["audioContent"]))
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")[:400].replace(key, "<key>")
        sys.exit(f"chirp: HTTP {e.code} for {voice}: {msg}")


def elevenlabs(text: str, voice: str, speed: float, out: Path) -> None:
    """ElevenLabs text-to-speech. `voice` is a voice id from the ElevenLabs voice library.
    The API key is read from ~/.elevenlabs_key (never printed). Starter tier allows mp3 up to 128 kbps (PCM is Pro+)."""
    key = ELEVEN_KEY_FILE.read_text().strip()
    body = {"text": text, "model_id": ELEVEN_MODEL,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0,
                               "use_speaker_boost": True, "speed": max(0.7, min(1.2, speed))}}
    req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"xi-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            mp3 = r.read()
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")[:400].replace(key, "<key>")
        sys.exit(f"elevenlabs: HTTP {e.code} for {voice}: {msg}")
    mp3_path = out.with_suffix(".mp3")
    mp3_path.write_bytes(mp3)
    sh(["ffmpeg", "-y", "-i", str(mp3_path), str(out)])
    mp3_path.unlink()


# Written form -> spoken form, applied only to the text sent to TTS (the screen keeps the written form).
PRONOUNCE = FILM.get("pronounce", {})


def spoken(text: str) -> str:
    for word in sorted(PRONOUNCE, key=len, reverse=True):  # serpapi_fdw before SerpApi
        text = re.sub(rf"(?<![\w-]){re.escape(word)}(?![\w-]|\.\w)", PRONOUNCE[word], text, flags=re.IGNORECASE)
    return text


def synth(seg_id: str, text: str) -> Path:
    """One narration line -> 48 kHz stereo WAV, loudness-normalised for a keynote mix."""
    out = AUDIO / f"{seg_id}.wav"
    text = spoken(text)
    if ENGINE == "kokoro":
        for stale in AUDIO.glob(f"{seg_id}_raw_*.wav"):
            stale.unlink()
        env = dict(os.environ, VIRTUAL_ENV=str(TTS_PY.parent.parent), PATH=f"{TTS_PY.parent}:{os.environ['PATH']}")
        subprocess.run([str(TTS_PY), "-m", "mlx_audio.tts.generate", "--model", "mlx-community/Kokoro-82M-bf16",
                        "--text", text, "--voice", VOICE, "--speed", str(SPEED), "--lang_code", "a",
                        "--output_path", str(AUDIO), "--file_prefix", f"{seg_id}_raw", "--audio_format", "wav"],
                       check=True, capture_output=True, text=True, env=env)
        parts = sorted(AUDIO.glob(f"{seg_id}_raw_*.wav"))
        if not parts:
            sys.exit(f"kokoro produced nothing for {seg_id}")
        if len(parts) == 1:
            raw = parts[0]
        else:  # long lines come back in sentence chunks; stitch them
            lst = AUDIO / f"{seg_id}_parts.txt"
            lst.write_text("".join(f"file '{q.as_posix()}'\n" for q in parts))
            raw = AUDIO / f"{seg_id}_raw.wav"
            sh(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(raw)])
    elif ENGINE == "chirp":
        raw = AUDIO / f"{seg_id}_raw.wav"
        chirp(text, VOICE, SPEED, raw)
    elif ENGINE == "elevenlabs":  # paid per character: reuse a take unless engine, voice, model, speed or text changed
        tag = hashlib.sha1(json.dumps([VOICE, ELEVEN_MODEL, SPEED, text]).encode()).hexdigest()[:12]
        raw = AUDIO / "eleven_cache" / f"{tag}.wav"
        if not raw.exists():
            raw.parent.mkdir(exist_ok=True)
            elevenlabs(text, VOICE, SPEED, raw)
    else:
        raw = AUDIO / f"{seg_id}.aiff"
        sh(["say", "-v", VOICE, "-r", "165", "-o", str(raw), text])
    sh(["ffmpeg", "-y", "-i", str(raw), "-af", "aresample=48000:resampler=soxr,loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ar", "48000", "-ac", "2", str(out)])
    return out


def synth_all(segments: list[dict]) -> dict[str, Path]:
    """Every narration line -> wav, before any clip is cut, so shots can be sized to the voice."""
    if ENGINE == "say" and shutil.which("say") is None:
        return {}
    wavs = {}
    for seg in segments:
        text = seg.get("vo", "").strip()
        if text:
            wavs[seg["id"]] = synth(seg["id"], text)
            print(f"  vo {seg['id']:<16} {duration(wavs[seg['id']]):5.1f}s", flush=True)
    return wavs


def narration(segments: list[dict], starts: list[float], total: float, wavs: dict[str, Path]) -> Path | None:
    inputs, filters, idx = [], [], 0
    for seg, start in zip(segments, starts):
        wav = wavs.get(seg["id"])
        if not wav:
            continue
        inputs += ["-i", str(wav)]
        ms = int((start + 0.4) * 1000)
        filters.append(f"[{idx}:a]adelay={ms}|{ms}[a{idx}]")
        idx += 1
    if idx == 0:
        return None
    mix = "".join(f"[a{i}]" for i in range(idx)) + f"amix=inputs={idx}:normalize=0,apad=whole_dur={total:.2f}[out]"
    track = AUDIO / "narration.m4a"
    sh(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filters) + ";" + mix, "-map", "[out]",
        "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.2f}", str(track)])
    return track


# ---------------------------------------------------------------- assemble

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-tapes", action="store_true")
    ap.add_argument("--only", help="render only this tape/browser scene id and exit")
    ap.add_argument("--no-voice", action="store_true")
    ap.add_argument("--audition", metavar="TEXT", help="synthesise TEXT with each --voices voice into out/audition and exit")
    ap.add_argument("--voices", default="", help="comma-separated voice ids for --audition")
    ap.add_argument("--engine", help="override film.json voice_engine (kokoro, chirp, elevenlabs, say)")
    args = ap.parse_args()
    global ENGINE, VOICE
    if args.engine:
        ENGINE = args.engine
    if args.audition:
        (OUT / "audition").mkdir(exist_ok=True)
        for v in [x.strip() for x in args.voices.split(",") if x.strip()]:
            VOICE = v
            wav = synth(f"audition_{v}", args.audition)
            dst = OUT / "audition" / f"{ENGINE}_{v}.wav"
            shutil.move(wav, dst)
            print(f"  {dst.name}  {duration(dst):.1f}s")
        return 0

    if args.only:
        kind = next((x["type"] for x in FILM["segments"] if x["id"] == args.only), "tape")
        RENDER.get(kind, render_tape)(args.only)
        return 0

    segs = FILM["segments"]
    if not args.skip_tapes:
        print("cards")
        sh([sys.executable, str(DEMO / "cards" / "render.py")])
        print("tapes")
        for seg in segs:
            if seg["type"] in RENDER:
                RENDER[seg["type"]](seg["id"])

    wavs = {} if args.no_voice else synth_all(segs)
    print("clips")
    clips: list[Path] = []
    for seg in segs:
        need = duration(wavs[seg["id"]]) + 0.4 + VO_PAD if seg["id"] in wavs else 0.0
        clips.append(card_clip(seg, need) if seg["type"] == "card" else tape_clip(seg, need))
        d = duration(clips[-1])
        if seg["type"] != "card" and need > 0 and d + 0.05 >= need and need > duration(source(seg)):
            print(f"  held last frame of {seg['id']} to {d:.1f}s for the narration")

    starts, t = [], 0.0
    for c in clips:
        starts.append(t)
        t += duration(c)
    total = t

    concat = OUT / "concat.txt"
    concat.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips))
    silent = OUT / "film-silent.mp4"
    sh(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(silent)])

    final = ROOT / FILM["output"] if not Path(FILM["output"]).is_absolute() else Path(FILM["output"])
    final = DEMO / FILM["output"]
    track = None if args.no_voice else narration(segs, starts, total, wavs)
    if track:
        sh(["ffmpeg", "-y", "-i", str(silent), "-i", str(track), "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-shortest", str(final)])
    else:
        shutil.copy(silent, final)

    timeline = OUT / "timeline.txt"
    lines = ["# start  dur   segment           voice-over line", ]
    for seg, s, c in zip(segs, starts, clips):
        lines.append(f"{s:6.1f}s {duration(c):5.1f}s  {seg['id']:<16}  {seg.get('vo','')}")
    lines.append(f"# total {total:.1f}s (limit 180s)")
    timeline.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nwrote {final} ({total:.1f}s) and {timeline}")
    if total > 180:
        print("WARNING: over three minutes", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
