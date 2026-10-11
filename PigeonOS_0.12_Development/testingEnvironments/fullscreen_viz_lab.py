"""Fullscreen visualizer lab: find looks for the encoder presets at 1280×800.

Runs the real renderer (:mod:`pigeon.fullscreen_viz`), so what you see — and
the render time in the HUD — is what the Pi's renderer costs. Tuned presets
save to ``fullscreen_viz.json`` in the Pigeon state dir, which the app reads.

Run::

    testingEnvironments/run_fullscreen_viz_lab.command
    # or, from pigeonSystem with its venv:
    .venv/bin/python ../../testingEnvironments/fullscreen_viz_lab.py [--audio synth|pink|sweep|tone|mic|FILE]

Encoder (simulated)
    ← / → , [ / ], mouse wheel    turn: previous / next preset
    mouse button                  press: click = short press (Settings in the app),
                                  hold ≥ 0.6 s = long press (Now Playing ↔ visualizer)
    Space / Return, L             short press, long press
Lab
    T  tuner window (sliders, colors, save to the app)
    Z  zone-6 preview (the preset scaled into zone 6 of the now-playing layout)
    A  cycle audio source         M  mute / unmute playback
    H  HUD (render ms)            F  fullscreen window
    S  save a PNG                 Esc / Q  quit

The tuner edits a working copy (``fullscreen_viz_lab.json`` in the state
dir) that the viewer follows live; "Save to app" writes ``fullscreen_viz.json``.

Headless::

    fullscreen_viz_lab.py --bench           # ms/frame per preset at 1280×800 and zone 6, zone 4 for reference
    fullscreen_viz_lab.py --snapshots DIR   # PNG of every preset (full + zone 6)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path


def _pigeon_system_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "Pigeon" / "pigeonSystem"


sys.path.insert(0, str(_pigeon_system_dir()))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from pigeon import fullscreen_viz as fv  # noqa: E402
from pigeon import zone4_eq  # noqa: E402

SR = 48_000
LONG_PRESS_S = 0.6
AUDIO_SOURCES = ("synth", "pink", "sweep", "tone", "mic")


# ---------------------------------------------------------------------------
# Test signals (pre-rendered loops, stereo float32)
# ---------------------------------------------------------------------------
def _env(n: int, attack: float, decay: float) -> np.ndarray:
    t = np.arange(n) / SR
    return np.minimum(1.0, t / max(1e-4, attack)) * np.exp(-t / decay)


def synth_music(seconds: float = 8.0, seed: int = 7) -> np.ndarray:
    """120 BPM drum/bass/chord loop with stereo spread, peaking near 0 dBFS."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    out = np.zeros((n, 2), np.float32)
    beat = SR // 2  # 120 BPM
    t = np.arange(n) / SR

    def add(start: int, sig: np.ndarray, pan: float = 0.0) -> None:
        end = min(n, start + sig.size)
        seg = sig[: end - start]
        out[start:end, 0] += seg * math.sqrt(0.5 * (1.0 - pan))
        out[start:end, 1] += seg * math.sqrt(0.5 * (1.0 + pan))

    kick_n = int(0.35 * SR)
    kt = np.arange(kick_n) / SR
    kick = np.sin(2 * np.pi * (45 * kt + 60 * (1 - np.exp(-kt * 30)) / 30)) * _env(kick_n, 0.002, 0.12)
    snare_n = int(0.25 * SR)
    snare_noise = rng.standard_normal(snare_n)
    snare_noise = snare_noise - np.convolve(snare_noise, np.ones(4) / 4, "same")
    snare = (0.6 * snare_noise + 0.5 * np.sin(2 * np.pi * 190 * np.arange(snare_n) / SR)) * _env(snare_n, 0.001, 0.06)
    hat_n = int(0.06 * SR)
    hat = rng.standard_normal(hat_n)
    hat = (hat - np.convolve(hat, np.ones(2) / 2, "same")) * _env(hat_n, 0.0005, 0.015)
    roots = (55.0, 55.0, 43.65, 49.0)  # A, A, F, G
    chords = ((220.0, 261.63, 329.63), (220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (196.0, 246.94, 293.66))
    for b in range(int(seconds * 2)):
        s = b * beat
        add(s, 0.95 * kick) if b % 2 == 0 else add(s, 0.7 * snare, 0.1)
        for eighth in range(2):
            add(s + eighth * beat // 2, 0.25 * hat, -0.5 + (b % 4) * 0.3)
    bar_n = beat * 4
    for bar in range(int(seconds / 2)):
        s = bar * bar_n
        f = roots[bar % 4]
        for k in range(8):
            note_n = beat // 2
            nt = np.arange(note_n) / SR
            ff = f * (2.0 if k % 4 == 3 else 1.0)
            saw = 2 * ((nt * ff) % 1.0) - 1
            saw = np.convolve(saw, np.ones(12) / 12, "same")
            add(s + k * note_n, 0.35 * saw * _env(note_n, 0.005, 0.18))
        pad_t = t[s : s + bar_n] - t[s]
        pad = sum(np.sin(2 * np.pi * fr * pad_t + i) for i, fr in enumerate(chords[bar % 4]))
        pad = 0.07 * pad * np.minimum(1.0, pad_t / 0.4)
        end = min(n, s + bar_n)
        m = end - s
        out[s:end, 0] += (pad[:m] * (1.0 + 0.3 * np.sin(2 * np.pi * 0.5 * pad_t[:m]))).astype(np.float32)
        out[s:end, 1] += (pad[:m] * (1.0 - 0.3 * np.sin(2 * np.pi * 0.5 * pad_t[:m] + 0.7))).astype(np.float32)
    # A crescendo into the last bar so meters reach the red and clip lights once.
    ramp = 0.55 + 0.47 * np.clip((t - seconds * 0.5) / (seconds * 0.5), 0.0, 1.0)
    out *= ramp[:, None].astype(np.float32)
    return np.clip(out / max(1e-6, float(np.abs(out).max())) * 1.02, -1.0, 1.0).astype(np.float32)


def pink_noise(seconds: float = 4.0, seed: int = 3) -> np.ndarray:
    """Uncorrelated stereo pink noise at about −18 dBFS RMS (an RTA should read flat)."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    out = np.zeros((n, 2), np.float32)
    f = np.fft.rfftfreq(n, 1.0 / SR)
    shape = 1.0 / np.sqrt(np.maximum(f, 10.0))
    for c in range(2):
        spec = np.fft.rfft(rng.standard_normal(n)) * shape
        x = np.fft.irfft(spec, n)
        out[:, c] = x / np.sqrt(np.mean(x * x)) * 10 ** (-18 / 20)
    return out


def sine_sweep(seconds: float = 8.0) -> np.ndarray:
    """Log sweep 20 Hz → 20 kHz, mono."""
    t = np.arange(int(SR * seconds)) / SR
    k = math.log(20000 / 20)
    x = 0.5 * np.sin(2 * np.pi * 20 * seconds / k * (np.exp(t / seconds * k) - 1))
    return np.stack((x, x), axis=1).astype(np.float32)


def cal_tone(seconds: float = 6.0) -> np.ndarray:
    """1 kHz at −18 dBFS RMS: both, then L only, then R only (VU should sit on 0)."""
    t = np.arange(int(SR * seconds)) / SR
    x = (10 ** (-18 / 20) * math.sqrt(2) * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    third = x.size // 3
    out = np.stack((x, x), axis=1)
    out[third : 2 * third, 1] = 0.0
    out[2 * third :, 0] = 0.0
    return out


def load_audio_file(path: str) -> np.ndarray:
    """Stereo float32 at 48 kHz. Non-WAV files go through ``afconvert`` (macOS) or ``ffmpeg``."""
    src = Path(path).expanduser()
    wav = src
    tmp_dir = None
    if src.suffix.lower() not in (".wav", ".wave"):
        tmp_dir = tempfile.mkdtemp(prefix="pigeon_viz_lab_")
        wav = Path(tmp_dir) / "audio.wav"
        if shutil.which("afconvert"):
            cmd = ["afconvert", "-f", "WAVE", "-d", "LEI16@48000", "-c", "2", str(src), str(wav)]
        elif shutil.which("ffmpeg"):
            cmd = ["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-ac", "2", "-ar", "48000", str(wav)]
        else:
            raise SystemExit("Need a .wav file (no afconvert / ffmpeg to convert others).")
        subprocess.run(cmd, check=True)
    with wave.open(str(wav), "rb") as wf:
        ch, width, rate, n = wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()
        raw = wf.readframes(n)
    if tmp_dir:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    if width == 2:
        x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
    elif width == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        x = ((b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16)) << 8 >> 8)
        x = x.astype(np.float32) / 8388608.0
    elif width == 4:
        x = np.frombuffer(raw, "<i4").astype(np.float32) / 2147483648.0
    else:
        raise SystemExit(f"Unsupported WAV sample width: {width}")
    x = x.reshape(-1, ch)
    x = np.repeat(x, 2, axis=1) if ch == 1 else x[:, :2]
    if rate != SR:
        idx = np.arange(0, x.shape[0] - 1, rate / SR)
        x = np.stack([np.interp(idx, np.arange(x.shape[0]), x[:, c]) for c in range(2)], axis=1)
    return np.ascontiguousarray(x, np.float32)


# ---------------------------------------------------------------------------
# Feeder: loops a buffer into the zone-4 PCM ring in real time (and plays it)
# ---------------------------------------------------------------------------
class Feeder:
    def __init__(self) -> None:
        self.buf: np.ndarray | None = None
        self.pos = 0
        self.muted = True
        self._lock = threading.Lock()
        self._stream = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def set_buffer(self, buf: np.ndarray | None, audible: bool) -> None:
        with self._lock:
            self.buf, self.pos, self.muted = buf, 0, not audible
        if buf is not None:
            self._ensure_running()

    def _next(self, n: int) -> np.ndarray:
        with self._lock:
            buf = self.buf
            if buf is None:
                return np.zeros((n, 2), np.float32)
            idx = (self.pos + np.arange(n)) % buf.shape[0]
            self.pos = (self.pos + n) % buf.shape[0]
            return buf[idx]

    def _ensure_running(self) -> None:
        if self._stream is not None or self._thread is not None:
            return
        try:
            import sounddevice as sd  # type: ignore[import-not-found]

            def cb(outdata, frames, _t, _status) -> None:
                x = self._next(frames)
                if self.buf is not None:
                    zone4_eq.feed_pcm_stereo(x[:, 0], x[:, 1], float(SR))
                outdata[:] = 0.0 if self.muted else x

            self._stream = sd.OutputStream(samplerate=SR, channels=2, dtype="float32", blocksize=512, callback=cb)
            self._stream.start()
            return
        except Exception as exc:  # no output device / no sounddevice: pace with a thread, silently
            print(f"lab: audio output unavailable ({exc}); feeding silently", file=sys.stderr)
            self._stream = None

        def run() -> None:
            nxt = time.monotonic()
            while not self._stop.is_set():
                x = self._next(512)
                if self.buf is not None:
                    zone4_eq.feed_pcm_stereo(x[:, 0], x[:, 1], float(SR))
                nxt += 512 / SR
                time.sleep(max(0.0, nxt - time.monotonic()))

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass


def source_buffer(name: str, file_buf: np.ndarray | None) -> tuple[np.ndarray | None, bool]:
    """``(buffer, audible by default)`` for an audio source name."""
    if name == "synth":
        return synth_music(), False
    if name == "pink":
        return pink_noise(), False
    if name == "sweep":
        return sine_sweep(), False
    if name == "tone":
        return cal_tone(), False
    if name == "file":
        return file_buf, True
    return None, False  # mic


# ---------------------------------------------------------------------------
# Zone-6 preview frame
# ---------------------------------------------------------------------------
def zone6_backdrop(w: int, h: int) -> np.ndarray:
    """A stand-in now-playing layout (zone outlines) at ``w×h``."""
    from pigeon.widgets.view_circles import _zone_spec  # type: ignore[attr-defined]

    img = np.zeros((h, w, 3), np.uint8)
    xf = fv.Xf(w, h)
    for i in (3, 4, 5):
        z = _zone_spec(i)
        fv._rrect(img, int(round(xf.x(z.x + 6))), int(round(xf.y(z.y + 6))), int(round(xf.x(z.x + z.w - 6))),
                  int(round(xf.y(z.y + z.h - 6))), int(round(xf.l(13))), (0x1A, 0x1A, 0x1A), aa=True)
    return img


def zone6_rect(w: int, h: int) -> tuple[int, int, int, int, int]:
    xf = fv.Xf(w, h)
    x, y, zw, zh, r = fv.ZONE6_RECT
    return (int(round(xf.x(x))), int(round(xf.y(y))), int(round(xf.l(zw))), int(round(xf.l(zh))),
            int(round(xf.l(r))))


# ---------------------------------------------------------------------------
# Headless modes
# ---------------------------------------------------------------------------
def _feed_frame(buf: np.ndarray, pos: int, n: int) -> int:
    idx = (pos + np.arange(n)) % buf.shape[0]
    zone4_eq.feed_pcm_stereo(buf[idx, 0], buf[idx, 1], float(SR))
    return (pos + n) % buf.shape[0]


def _no_mic() -> None:
    zone4_eq.want_mic_capture = lambda: None  # headless: never open the mic


def bench(frames: int) -> int:
    _no_mic()
    buf = synth_music()
    fv.set_presets(fv.presets())
    viz = fv.FullscreenViz(0)
    full = np.zeros((fv.DESIGN_H, fv.DESIGN_W, 3), np.uint8)
    app = np.zeros((fv.DESIGN_H, fv.DESIGN_W, 4), np.uint8)
    z6 = zone6_rect(fv.DESIGN_W, fv.DESIGN_H)
    pos = 0
    print(f"{'preset':<16}{'size':<12}{'first ms':>10}{'mean ms':>10}{'p95 ms':>10}")

    def run(label: str, size: str, fn) -> None:
        nonlocal pos
        times = []
        for i in range(frames + 1):
            pos = _feed_frame(buf, pos, SR // 30)
            t0 = time.perf_counter()
            fn()
            times.append((time.perf_counter() - t0) * 1000.0)
        first, rest = times[0], np.array(times[1:])
        print(f"{label:<16}{size:<12}{first:>10.1f}{rest.mean():>10.2f}{np.percentile(rest, 95):>10.2f}")

    for i, p in enumerate(fv.presets()):
        viz.set_index(i, toast=False)
        run(str(p["name"])[:15], "1280x800", lambda: viz.render(full, capture=False, toast=False))
        run("", f"zone6 {z6[2]}x{z6[3]}", lambda: viz.render(app, z6, capture=False, toast=False))
    from pigeon.zone4_eq import Zone4EQ

    z4 = Zone4EQ()
    run("zone4 EQ (ref)", "1067x100", lambda: z4.render_into(app, (113, 536, 1067, 100, 13), 0.5))
    return 0


def snapshots(out_dir: str) -> int:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    _no_mic()
    buf = synth_music()
    fv.set_presets(fv.presets())
    viz = fv.FullscreenViz(0)
    pos = int(SR * 6.3)
    for i, p in enumerate(fv.presets()):
        viz.set_index(i, toast=False)
        viz.analysis = fv.Analysis()
        full = np.zeros((fv.DESIGN_H, fv.DESIGN_W, 3), np.uint8)
        z6 = zone6_backdrop(fv.DESIGN_W, fv.DESIGN_H)
        for _ in range(45):  # 1.5 s of frames so ballistics settle
            pos = _feed_frame(buf, pos, SR // 30)
            viz._last_t = time.monotonic() - 1 / 30
            viz.render(full, capture=False, toast=False)
        viz._last_t = time.monotonic() - 1 / 30
        viz.render(z6, zone6_rect(fv.DESIGN_W, fv.DESIGN_H), capture=False, toast=False)
        slug = f"{i + 1}_{str(p['name']).lower().replace(' ', '_')}"
        cv2.imwrite(str(d / f"{slug}.png"), full)
        cv2.imwrite(str(d / f"{slug}_zone6.png"), z6)
        print(d / f"{slug}.png")
    return 0


# ---------------------------------------------------------------------------
# Working presets, shared by the viewer and the tuner window (two processes)
# ---------------------------------------------------------------------------
WORK_NAME = "fullscreen_viz_lab.json"


def work_path() -> Path:
    return fv.pigeon_state_dir() / WORK_NAME


def work_mtime() -> int | None:
    try:
        return work_path().stat().st_mtime_ns
    except OSError:
        return None


def write_work(items: list[dict], active: int) -> None:
    path = work_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"active": int(active), "presets": items}, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_work() -> tuple[list[dict], int]:
    """Working presets; seeded from the app's saved presets the first time."""
    try:
        raw = json.loads(work_path().read_text(encoding="utf-8"))
        items = [fv.complete_preset(dict(x)) for x in raw["presets"]
                 if isinstance(x, dict) and x.get("style") in fv.STYLES]  # retired styles drop out
        if items:
            return items, int(raw.get("active", 0)) % len(items)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    items, active = fv._read_config()
    write_work(items, active)
    return items, active


def saved_presets() -> list[dict]:
    return fv._read_config()[0]


# ---------------------------------------------------------------------------
# Viewer (OpenCV window: ~60 fps on macOS, where a Tk image redraw costs ~30 ms)
# ---------------------------------------------------------------------------
WIN = "Pigeon - fullscreen visualizer lab"
_KEYS_LEFT = {63234, 65361, 2424832, ord("["), ord(",")}
_KEYS_RIGHT = {63235, 65363, 2555904, ord("]"), ord(".")}


class Viewer:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.w, self.h = args.width, args.height
        self.items, active = read_work()
        fv.set_presets(self.items)
        self.viz = fv.FullscreenViz(active)
        self.seen_mtime = work_mtime()
        self.unsaved = self.items != saved_presets()
        self.mode = "viz"  # or "now playing"
        self.zone6 = args.zone6
        self.hud = True
        self.frame = np.zeros((self.h, self.w, 3), np.uint8)
        self.backdrop = zone6_backdrop(self.w, self.h)
        self.times: list[float] = []
        self.present_ms = 0.0
        self.message, self.message_until = "", 0.0
        self.press_t: float | None = None
        self.long_fired = False
        self.wheel_t = 0.0
        self.tuner: subprocess.Popen | None = None
        self.quit_now = False
        self._poll_t = 0.0

        self.file_buf = load_audio_file(args.audio) if args.audio not in AUDIO_SOURCES else None
        self.sources = list(AUDIO_SOURCES) + (["file"] if self.file_buf is not None else [])
        self.source = "file" if self.file_buf is not None else args.audio
        self.feeder = Feeder()
        self._apply_source()

        print(__doc__.split("Headless")[0], file=sys.stderr)
        self.viz.prewarm(self.w, self.h)
        cv2.namedWindow(WIN, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO | cv2.WINDOW_GUI_NORMAL)
        cv2.resizeWindow(WIN, self.w, self.h)
        cv2.setMouseCallback(WIN, self._mouse)
        self.viz.show_toast()
        if args.tuner_open:
            self.open_tuner()

    # -- audio --------------------------------------------------------------------
    def _apply_source(self) -> None:
        buf, audible = source_buffer(self.source, self.file_buf)
        if self.source != "mic":
            zone4_eq.stop_mic_capture()
        self.feeder.set_buffer(buf, audible)
        self.flash(f"Audio: {self.source}" + ("" if self.source == "mic" else " (muted)" if not audible else ""))

    def cycle_source(self) -> None:
        self.source = self.sources[(self.sources.index(self.source) + 1) % len(self.sources)]
        self._apply_source()

    def toggle_mute(self) -> None:
        if self.source == "mic":
            return
        self.feeder.muted = not self.feeder.muted
        self.flash("Muted" if self.feeder.muted else "Playing through speakers")

    # -- encoder ------------------------------------------------------------------
    def turn(self, step: int) -> None:
        if self.mode != "viz":
            self.flash("Encoder turn (Now Playing: volume / browse)")
            return
        self.viz.rotate(step)
        items, _active = read_work()  # keep any edit the tuner just wrote
        self.items[:] = items
        write_work(self.items, self.viz.index)
        self.seen_mtime = work_mtime()

    def short_press(self) -> None:
        self.flash("Short press -> Settings (in the app)")

    def long_press(self) -> None:
        self.mode = "now playing" if self.mode == "viz" else "viz"
        if self.mode == "viz":
            self.viz.show_toast()
        self.flash("Long press -> " + ("fullscreen visualizer" if self.mode == "viz" else "Now Playing"))

    def _mouse(self, event: int, _x: int, _y: int, flags: int, _param: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            self.press_t, self.long_fired = time.monotonic(), False
        elif event == cv2.EVENT_LBUTTONUP and self.press_t is not None:
            self.press_t = None
            if not self.long_fired:
                self.short_press()
        elif event == cv2.EVENT_MOUSEWHEEL:
            now = time.monotonic()
            if now - self.wheel_t > 0.15:  # a trackpad swipe sends many events: one detent each
                self.wheel_t = now
                self.turn(1 if cv2.getMouseWheelDelta(flags) < 0 else -1)

    def _check_long(self) -> None:
        if self.press_t is not None and not self.long_fired and time.monotonic() - self.press_t >= LONG_PRESS_S:
            self.long_fired = True
            self.long_press()

    # -- keys ---------------------------------------------------------------------
    def key(self, k: int) -> None:
        if k in _KEYS_LEFT:
            return self.turn(-1)
        if k in _KEYS_RIGHT:
            return self.turn(1)
        c = chr(k & 0xFF).lower() if 0 <= (k & 0xFF) < 128 else ""
        if k in (13, 10, 32):
            self.short_press()
        elif c == "l":
            self.long_press()
        elif c == "t":
            self.open_tuner()
        elif c == "z":
            self.zone6 = not self.zone6
            self.flash("Zone-6 preview" if self.zone6 else "Fullscreen")
        elif c == "a":
            self.cycle_source()
        elif c == "m":
            self.toggle_mute()
        elif c == "h":
            self.hud = not self.hud
        elif c == "f":
            full = cv2.getWindowProperty(WIN, cv2.WND_PROP_FULLSCREEN) == cv2.WINDOW_FULLSCREEN
            cv2.setWindowProperty(WIN, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL if full else cv2.WINDOW_FULLSCREEN)
        elif c == "s":
            self.save_png()
        elif k == 27 or c == "q":
            self.quit_now = True

    def open_tuner(self) -> None:
        if self.tuner is not None and self.tuner.poll() is None:
            self.flash("Tuner is already open")
            return
        self.tuner = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--tuner"])
        self.flash("Tuner opened")

    def save_png(self) -> None:
        d = fv.pigeon_state_dir() / "fullscreen_viz_captures"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{time.strftime('%Y%m%d-%H%M%S')}_{self.viz.preset()['name']}.png".replace(" ", "_")
        cv2.imwrite(str(path), self.frame)
        self.flash(f"Saved {path.name}")
        print(f"lab: saved {path}", file=sys.stderr)

    def flash(self, msg: str, secs: float = 2.0) -> None:
        self.message, self.message_until = msg, time.monotonic() + secs
        print(f"lab: {msg}", file=sys.stderr)

    # -- presets from the tuner -------------------------------------------------------
    def _poll_work(self) -> None:
        now = time.monotonic()
        if now - self._poll_t < 0.2:
            return
        self._poll_t = now
        m = work_mtime()
        if m == self.seen_mtime:
            return
        self.seen_mtime = m
        items, active = read_work()
        self.items[:] = items
        if active != self.viz.index:
            self.viz.set_index(active)
        self.unsaved = self.items != saved_presets()

    # -- loop -------------------------------------------------------------------------
    def run(self) -> None:
        period = 1.0 / self.args.fps
        nxt = time.monotonic()
        try:
            while not self.quit_now:
                self._poll_work()
                self._check_long()
                f = self.frame
                if self.mode != "viz":
                    self._draw_now_playing(f)
                elif self.zone6:
                    f[:] = self.backdrop
                    self.viz.render(f, zone6_rect(self.w, self.h), capture=self.source == "mic")
                else:
                    self.viz.render(f, capture=self.source == "mic")
                if self.mode == "viz":
                    self.times = (self.times + [self.viz.last_render_ms])[-90:]
                t0 = time.perf_counter()
                show = f.copy() if (self.hud or time.monotonic() < self.message_until) else f
                self._overlay(show)
                cv2.imshow(WIN, show)
                self.present_ms = (time.perf_counter() - t0) * 1000.0
                nxt += period
                if nxt < time.monotonic() - period:
                    nxt = time.monotonic()
                k = cv2.waitKeyEx(max(1, int((nxt - time.monotonic()) * 1000)))
                if k != -1:
                    self.key(k)
                try:
                    if cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:
                        break
                except cv2.error:
                    break
        finally:
            self.close()

    def close(self) -> None:
        self.feeder.close()
        zone4_eq.stop_mic_capture()
        if self.tuner is not None and self.tuner.poll() is None:
            self.tuner.terminate()
        cv2.destroyAllWindows()
        cv2.waitKey(1)
        if self.unsaved:
            print(f"lab: presets differ from the app's; they are kept in {work_path()} "
                  "(Save in the tuner writes them to the app).", file=sys.stderr)

    def _draw_now_playing(self, f: np.ndarray) -> None:
        f[:] = (0, 0, 0)
        for i, (text, size, col) in enumerate((("Now Playing", 1.4, (230, 230, 230)),
                                               ("hold the mouse button (or press L) for the visualizer", 0.7,
                                                (120, 120, 120)))):
            (tw, _th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, size, 2)
            cv2.putText(f, text, ((self.w - tw) // 2, self.h // 2 - 10 + i * 50), cv2.FONT_HERSHEY_SIMPLEX,
                        size, col, 2, cv2.LINE_AA)

    def _overlay(self, img: np.ndarray) -> None:
        lines = []
        if self.hud and self.mode == "viz":
            t = np.array(self.times or [0.0])
            p = self.viz.preset()
            lines.append(f"{self.viz.index + 1}/{len(self.items)}  {p['name']}  [{p['style']}]"
                         f"{'  * not saved to app' if self.unsaved else ''}")
            lines.append(f"render {t.mean():5.2f} ms  p95 {np.percentile(t, 95):5.2f}  |  "
                         f"{'zone 6' if self.zone6 else f'{self.w}x{self.h}'}  |  audio {self.source}"
                         f"  |  T tuner  Z zone6  A audio  H hud")
        if time.monotonic() < self.message_until:
            lines.append(self.message)
        for i, s in enumerate(lines):
            y = 22 + i * 20
            cv2.putText(img, s, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(img, s, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# Tuner window (its own process; talks to the viewer through the working file)
# ---------------------------------------------------------------------------
class Tuner:
    def __init__(self) -> None:
        import tkinter as tk

        self.tk = tk
        self.items, self.active = read_work()
        self.own_mtime = work_mtime()
        self._write_job = None
        self.root = tk.Tk()
        self.root.title("Fullscreen visualizer presets")
        self.root.geometry("460x900")
        top = tk.Frame(self.root)
        top.pack(fill=tk.X, padx=8, pady=6)
        self.listbox = tk.Listbox(top, height=max(5, len(self.items)), exportselection=False)
        self.listbox.pack(fill=tk.X)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        row = tk.Frame(self.root)
        row.pack(fill=tk.X, padx=8)
        for text, fn in (("Save to app", self.save), ("Revert to saved", self.revert),
                         ("Style defaults", self.defaults), ("Copy JSON", self.copy_json)):
            tk.Button(row, text=text, command=fn).pack(side=tk.LEFT, padx=2)
        self.status = tk.Label(self.root, anchor="w", fg="#888888")
        self.status.pack(fill=tk.X, padx=10)
        outer = tk.Frame(self.root)
        outer.pack(fill=tk.BOTH, expand=True, padx=4, pady=6)
        self.canvas = tk.Canvas(outer, highlightthickness=0)
        sb = tk.Scrollbar(outer, orient=tk.VERTICAL, command=self.canvas.yview)
        self.body = tk.Frame(self.canvas)
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.root.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.rebuild()
        self.root.after(250, self._poll)

    def run(self) -> None:
        self.root.mainloop()

    # -- file sync ------------------------------------------------------------------
    def _flush(self) -> None:
        self._write_job = None
        _items, active = read_work()  # the viewer owns "active" (encoder turns)
        write_work(self.items, active)
        self.own_mtime = work_mtime()
        if active != self.active:  # the encoder moved while we were saving: show that preset
            self.active = active
            self._select(active)
            self.rebuild_fields()
        self._update_status()

    def changed(self) -> None:
        if self._write_job is not None:
            self.root.after_cancel(self._write_job)
        self._write_job = self.root.after(60, self._flush)
        self._update_status()

    def _poll(self) -> None:
        m = work_mtime()
        if m != self.own_mtime and self._write_job is None:
            self.own_mtime = m
            items, active = read_work()
            presets_changed = items != self.items
            self.items = items
            if presets_changed:
                self.rebuild()
            elif active != self.active:
                self.active = active
                self._select(active)
                self.rebuild_fields()
            self.active = active
        self.root.after(250, self._poll)

    def _update_status(self) -> None:
        same = [fv.complete_preset(dict(p)) for p in self.items] == saved_presets()
        self.status.configure(text="Matches the app's saved presets" if same
                              else f"Not saved to the app yet (working copy: {WORK_NAME})")

    # -- actions --------------------------------------------------------------------
    def save(self) -> None:
        path = fv.save_config(self.items, self.active)
        self._update_status()
        self.status.configure(text=f"Saved → {path}")

    def revert(self) -> None:
        self.items = saved_presets()
        self.active = min(self.active, len(self.items) - 1)
        self.changed()
        self.rebuild()

    def defaults(self) -> None:
        p = self.items[self.active]
        base = next((d for d in fv.DEFAULT_PRESETS if d["style"] == p["style"]), {"style": p["style"]})
        self.items[self.active] = fv.complete_preset(dict(base, name=p["name"]))
        self.changed()
        self.rebuild_fields()

    def copy_json(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(json.dumps(self.items[self.active], indent=2))
        self.status.configure(text="Preset JSON copied to the clipboard")

    def _select(self, i: int) -> None:
        self.listbox.selection_clear(0, self.tk.END)
        self.listbox.selection_set(i)
        self.listbox.see(i)

    def _on_select(self, _e: object) -> None:
        sel = self.listbox.curselection()
        if sel and sel[0] != self.active:
            self.active = sel[0]
            write_work(self.items, self.active)  # the viewer follows
            self.own_mtime = work_mtime()
            self.rebuild_fields()

    def _row_text(self, i: int) -> str:
        p = self.items[i]
        return f"{i + 1}. {p['name']}  —  {fv.STYLES[p['style']]['label']}"

    def _set(self, key: str, value: object) -> None:
        p = self.items[self.editing]
        if p.get(key) == value:
            return
        p[key] = value
        if key == "name":
            self.listbox.delete(self.editing)
            self.listbox.insert(self.editing, self._row_text(self.editing))
            self._select(self.active)
        self.changed()

    def _set_style(self, style: str) -> None:
        p = self.items[self.editing]
        if style != p["style"]:
            base = next((d for d in fv.DEFAULT_PRESETS if d["style"] == style), {"style": style})
            self.items[self.editing] = fv.complete_preset(dict(base, name=p["name"]))
            self.changed()
            self.rebuild()

    # -- widgets ----------------------------------------------------------------------
    def rebuild(self) -> None:
        self.listbox.delete(0, self.tk.END)
        for i in range(len(self.items)):
            self.listbox.insert(self.tk.END, self._row_text(i))
        self._select(self.active)
        self.rebuild_fields()
        self._update_status()

    def rebuild_fields(self) -> None:
        tk = self.tk
        for c in self.body.winfo_children():
            c.destroy()
        # Widgets edit the preset they were built for, even if the encoder moves on.
        self.editing = self.active
        p = self.items[self.editing]
        r = 0

        def label(text: str) -> None:
            tk.Label(self.body, text=text, anchor="w").grid(row=r, column=0, sticky="w", padx=4)

        label("name")
        name = tk.StringVar(value=str(p["name"]))
        name.trace_add("write", lambda *_: self._set("name", name.get()))
        tk.Entry(self.body, textvariable=name, width=24).grid(row=r, column=1, sticky="we")
        r += 1
        label("style")
        style = tk.StringVar(value=str(p["style"]))
        tk.OptionMenu(self.body, style, *fv.STYLES.keys(), command=lambda v: self._set_style(str(v))).grid(
            row=r, column=1, sticky="w")
        r += 1
        for key, (default, spec) in fv.style_specs(str(p["style"])).items():
            label(key)
            kind = spec[0]
            val = p.get(key, default)
            if kind == "num":
                _, lo, hi, step = spec
                s = tk.Scale(self.body, from_=lo, to=hi, resolution=step, orient=tk.HORIZONTAL, length=240)
                s.set(val)
                s.configure(command=lambda v, k=key: self._set(k, float(v)))
                s.grid(row=r, column=1, sticky="we")
            elif kind == "color":
                self._color_field(r, key, str(val))
            elif kind == "bool":
                var = tk.BooleanVar(value=bool(val))
                tk.Checkbutton(self.body, variable=var, command=lambda k=key, v=var: self._set(k, bool(v.get()))).grid(
                    row=r, column=1, sticky="w")
            elif kind == "choice":
                opts = spec[1]
                var = tk.StringVar(value=str(val))
                tk.OptionMenu(self.body, var, *[str(o) for o in opts],
                              command=lambda v, k=key, o=opts: self._set(k, next(x for x in o if str(x) == v))).grid(
                    row=r, column=1, sticky="w")
            else:
                var = tk.StringVar(value=str(val))
                var.trace_add("write", lambda *_, k=key, v=var: self._set(k, v.get()))
                tk.Entry(self.body, textvariable=var, width=12).grid(row=r, column=1, sticky="w")
            r += 1

    def _color_field(self, row: int, key: str, val: str) -> None:
        tk = self.tk
        f = tk.Frame(self.body)
        f.grid(row=row, column=1, sticky="w")
        var = tk.StringVar(value=val)
        sw = tk.Label(f, width=3, bg=val, relief=tk.SUNKEN)

        def apply(*_: object) -> None:
            s = var.get().strip()
            if len(s) in (4, 7) and s.startswith("#"):
                try:
                    sw.configure(bg=s)
                except tk.TclError:
                    return
                self._set(key, s.upper())

        def pick() -> None:
            from tkinter import colorchooser

            got = colorchooser.askcolor(color=var.get(), parent=self.root)[1]
            if got:
                var.set(got.upper())

        var.trace_add("write", apply)
        tk.Entry(f, textvariable=var, width=9).pack(side=tk.LEFT)
        sw.pack(side=tk.LEFT, padx=4)
        tk.Button(f, text="…", command=pick, width=2).pack(side=tk.LEFT)


# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fullscreen visualizer preset lab.")
    ap.add_argument("--audio", default="synth",
                    help=f"one of {', '.join(AUDIO_SOURCES)} or a path to an audio file (default synth)")
    ap.add_argument("--width", type=int, default=fv.DESIGN_W)
    ap.add_argument("--height", type=int, default=fv.DESIGN_H)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--zone6", action="store_true", help="start in the zone-6 preview")
    ap.add_argument("--tuner-open", action="store_true", help="open the tuner window at start")
    ap.add_argument("--tuner", action="store_true", help=argparse.SUPPRESS)  # the tuner process itself
    ap.add_argument("--bench", action="store_true", help="print render timings and exit")
    ap.add_argument("--frames", type=int, default=150, help="frames per bench run")
    ap.add_argument("--snapshots", metavar="DIR", help="write a PNG per preset and exit")
    args = ap.parse_args(argv)
    if args.bench:
        return bench(args.frames)
    if args.snapshots:
        return snapshots(args.snapshots)
    if args.tuner:
        Tuner().run()
        return 0
    Viewer(args).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
