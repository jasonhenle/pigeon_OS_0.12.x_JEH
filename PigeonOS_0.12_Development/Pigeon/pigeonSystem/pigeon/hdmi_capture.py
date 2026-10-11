"""HDMI capture card: signal presence and frame-change tracking.

Pigeon no longer reads text off the HDMI feed (OCR was retired). The capture
card is still used to:

- tell whether an HDMI signal is present (keeping now-playing up when an app is
  foreground but the player gives no title; the metadata inspector's HDMI
  page), and
- fingerprint a frame every few seconds so ``CLOCK_SAVER_FRAME_STREAK``
  unchanged frames in a row can arm the HDMI-driven clock saver.

Frame checks run off the UI thread, at most one at a time.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

CAPTURE_INDEX = 0
PREFERRED_WIDTH = 1920
PREFERRED_HEIGHT = 1080
# How often to fingerprint an HDMI frame while content is up.
FRAME_CHECK_INTERVAL_S = 5.0
# Unchanged HDMI frames in a row before HDMI-driven clock saver arms
# (24 x 5 s = 2 minutes).
CLOCK_SAVER_FRAME_STREAK = 24
# Mean abs diff (0–255) above this → frame considered changed.
_FRAME_DIFF_MEAN_MIN = 6.0
_FRAME_FP_W = 48
_FRAME_FP_H = 27

_HDMI_NAME_HINTS = (
    "blueavs",
    "hdmi",
    "capture",
    "usb video",
    "av to usb",
    "magewell",
    "elgato",
    "cam link",
    "video capture",
)
_SKIP_NAME_HINTS = (
    "facetime",
    "isight",
    "iphone",
    "ipad",
    "continuity",
    "studio display",
    "desk view",
    "macbook",
    "built-in",
)

# ``changed`` is None when no frame could be read.
OnFrameChecked = Callable[["bool | None"], None]


@dataclass
class FrameSchedule:
    last_check_mono: float = 0.0
    in_flight: bool = False
    last_frame_fp: Any = None
    consecutive_unchanged: int = 0
    last_frame_changed: bool = False


_schedule = FrameSchedule()


def reset_frame_schedule() -> None:
    """Clear cadence and frame memory (tests, HDMI off)."""
    global _schedule
    _schedule = FrameSchedule()


def hdmi_unchanged_streak() -> int:
    """How many consecutive frame checks saw an unchanged HDMI frame."""
    return int(_schedule.consecutive_unchanged)


def hdmi_clock_saver_due() -> bool:
    """True after ``CLOCK_SAVER_FRAME_STREAK`` unchanged HDMI frames in a row."""
    return int(_schedule.consecutive_unchanged) >= CLOCK_SAVER_FRAME_STREAK


def hdmi_last_frame_changed() -> bool:
    """True when the most recent frame differed from the prior fingerprint."""
    return bool(_schedule.last_frame_changed)


def _frame_fingerprint(frame) -> Any:
    """Small grayscale downsample used to detect HDMI content changes."""
    try:
        import cv2
        import numpy as np

        if frame is None or not getattr(frame, "size", 0):
            return None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        small = cv2.resize(
            gray, (_FRAME_FP_W, _FRAME_FP_H), interpolation=cv2.INTER_AREA
        )
        return small.astype(np.float32)
    except Exception:
        return None


def _note_frame_fingerprint(frame) -> bool:
    """Compare ``frame`` to the last fingerprint. Returns True if changed."""
    fp = _frame_fingerprint(frame)
    prev = _schedule.last_frame_fp
    changed = True
    if fp is not None and prev is not None:
        try:
            import numpy as np

            diff = float(np.mean(np.abs(fp - prev)))
            changed = diff >= _FRAME_DIFF_MEAN_MIN
        except Exception:
            changed = True
    if fp is not None:
        _schedule.last_frame_fp = fp
    if changed:
        _schedule.consecutive_unchanged = 0
        _schedule.last_frame_changed = True
    else:
        _schedule.consecutive_unchanged = int(_schedule.consecutive_unchanged) + 1
        _schedule.last_frame_changed = False
    return bool(_schedule.last_frame_changed)


_lock = threading.Lock()
_cap = None
_cap_index: int | None = None
_av_devices_cache: list[tuple[int, str, str]] | None = None
_hdmi_present: bool | None = None
_hdmi_probe_mono: float = 0.0
_hdmi_probe_in_flight: bool = False
_hdmi_no_signal_hits: int = 0
_HDMI_PROBE_TTL_S = 1.5
# Near-black, near-flat frames (typical HDMI-unplug output from a USB dongle).
_NO_SIGNAL_MEAN_MAX = 8.0
_NO_SIGNAL_STD_MAX = 4.0
_NO_SIGNAL_HITS_TO_DROP = 2


def frame_check_due(now: float | None = None) -> bool:
    """True every ``FRAME_CHECK_INTERVAL_S`` (the first call is always due)."""
    now = time.monotonic() if now is None else now
    if _schedule.last_check_mono and (now - _schedule.last_check_mono) < FRAME_CHECK_INTERVAL_S:
        return False
    _schedule.last_check_mono = now
    return True


def request_frame_check(on_done: OnFrameChecked) -> bool:
    """Start one background frame check. False if HDMI is absent or busy."""
    if not hdmi_capture_available():
        # Keep probing so a re-plug (or signal return) can turn the LED green.
        probe_hdmi_presence()
        return False
    with _lock:
        if _schedule.in_flight:
            return False
        _schedule.in_flight = True
    thread = threading.Thread(
        target=_frame_check_worker,
        args=(on_done,),
        name="hdmi-frame-check",
        daemon=True,
    )
    thread.start()
    return True


def _frame_check_worker(on_done: OnFrameChecked) -> None:
    changed: bool | None = None
    try:
        frame = _grab_frame()
        if frame is None:
            _schedule.last_frame_changed = True
            _schedule.consecutive_unchanged = 0
        else:
            changed = _note_frame_fingerprint(frame)
    except Exception:
        changed = None
    finally:
        with _lock:
            _schedule.in_flight = False
    try:
        on_done(changed)
    except Exception:
        pass


def release_capture() -> None:
    """Free the HDMI capture device so another process can use it."""
    reset_frame_schedule()
    with _lock:
        _drop_open_capture()


def _is_skip_camera(name: str, dtype: str = "") -> bool:
    blob = f"{name} {dtype}".lower()
    return any(skip in blob for skip in _SKIP_NAME_HINTS)


def _is_hdmi_camera(name: str, dtype: str = "") -> bool:
    if _is_skip_camera(name, dtype):
        return False
    low = name.lower()
    return any(hint in low for hint in _HDMI_NAME_HINTS)


def note_hdmi_present(present: bool) -> None:
    """Remember whether HDMI can currently deliver a video frame."""
    global _hdmi_present, _hdmi_no_signal_hits
    _hdmi_present = bool(present)
    if present:
        _hdmi_no_signal_hits = 0


def _linux_usb_video_indices() -> list[int]:
    """V4L2 indices of USB video devices — SoC codec/ISP nodes don't count.

    Raspberry Pi exposes a dozen /dev/video* nodes (bcm2835 codec/ISP, HEVC
    decoder) with nothing plugged in; a capture dongle is the only device
    whose sysfs path routes through the USB bus.
    """
    import glob
    import re as _re

    out: list[int] = []
    for sys_dir in sorted(glob.glob("/sys/class/video4linux/video*")):
        m = _re.search(r"video(\d+)$", sys_dir)
        if m is None:
            continue
        try:
            real = os.path.realpath(os.path.join(sys_dir, "device"))
        except OSError:
            continue
        if "/usb" in real:
            out.append(int(m.group(1)))
    return out


def hdmi_capture_available() -> bool:
    """True when HDMI can currently deliver a video frame to Pigeon.

    An open OpenCV handle is not enough: after the cable is pulled the capture
    often stays ``isOpened()`` (and the USB dongle may still enumerate), which
    used to leave the settings LED green with no picture coming in.
    """
    return bool(_hdmi_present)


def probe_hdmi_presence(*, force: bool = False) -> bool:
    """Return last known presence; refresh capture/signal in the background."""
    global _hdmi_probe_in_flight, _hdmi_probe_mono
    now = time.monotonic()
    stale = (
        force
        or _hdmi_probe_mono <= 0.0
        or (now - _hdmi_probe_mono) >= _HDMI_PROBE_TTL_S
    )
    if stale:
        with _lock:
            start = not _hdmi_probe_in_flight
            if start:
                _hdmi_probe_in_flight = True
        if start:
            threading.Thread(
                target=_hdmi_probe_worker, name="hdmi-probe", daemon=True
            ).start()
    return hdmi_capture_available()


def _frame_has_video_signal(frame) -> bool:
    """False for empty / near-black frames that cannot yield HDMI metadata."""
    if frame is None or not getattr(frame, "size", 0):
        return False
    try:
        import numpy as np

        arr = np.asarray(frame)
        if arr.size == 0:
            return False
        if arr.ndim == 3:
            gray = (
                arr[..., 0].astype(np.float32) * 0.114
                + arr[..., 1].astype(np.float32) * 0.587
                + arr[..., 2].astype(np.float32) * 0.299
            )
        else:
            gray = arr.astype(np.float32)
        step_y = max(1, int(gray.shape[0]) // 36)
        step_x = max(1, int(gray.shape[1]) // 64)
        sample = gray[::step_y, ::step_x]
        mean = float(sample.mean())
        std = float(sample.std())
        return mean > _NO_SIGNAL_MEAN_MAX or std > _NO_SIGNAL_STD_MAX
    except Exception:
        return True


def _hdmi_device_enumerated() -> bool:
    """True when a capture dongle is listed (USB present; signal not required)."""
    global _av_devices_cache
    if sys.platform == "darwin":
        _av_devices_cache = None
        named = _avfoundation_devices()
        return any(_is_hdmi_camera(name, dtype) for _i, name, dtype in named)
    if sys.platform.startswith("linux"):
        return bool(_linux_usb_video_indices())
    cached = _av_devices_cache
    if cached is not None:
        return any(_is_hdmi_camera(name, dtype) for _i, name, dtype in cached)
    return False


def _note_frame_signal(frame) -> bool:
    """Update presence from one grabbed frame. True when the frame has signal."""
    global _hdmi_no_signal_hits
    if frame is None or not getattr(frame, "size", 0):
        _hdmi_no_signal_hits = 0
        note_hdmi_present(False)
        return False
    if _frame_has_video_signal(frame):
        note_hdmi_present(True)
        return True
    _hdmi_no_signal_hits += 1
    if _hdmi_no_signal_hits >= _NO_SIGNAL_HITS_TO_DROP:
        note_hdmi_present(False)
        return False
    return bool(_hdmi_present)


def _read_open_capture():
    """One ``cap.read()`` from the current handle. ``None`` if it failed."""
    cap = _cap
    if cap is None:
        return None
    try:
        if not cap.isOpened():
            return None
        ok, frame = cap.read()
    except Exception:
        return None
    if not ok or frame is None or not getattr(frame, "size", 0):
        return None
    return frame


def _probe_hdmi_now() -> bool:
    """Check live HDMI signal; enumeration is a fallback when capture is dead.

    Fast path: read the already-open device (catches HDMI cable unplug without
    waiting on Swift / sysfs). An open handle alone never counts as present.
    """
    if _schedule.in_flight:
        return bool(_hdmi_present)

    frame = _read_open_capture()
    if frame is not None:
        return _note_frame_signal(frame)

    if _cap is not None:
        _drop_open_capture()
        note_hdmi_present(False)

    if not _hdmi_device_enumerated():
        note_hdmi_present(False)
        return False

    peeked = _grab_frame()
    if peeked is None:
        note_hdmi_present(False)
        return False
    return bool(_hdmi_present)


def _hdmi_probe_worker() -> None:
    global _hdmi_probe_in_flight, _hdmi_probe_mono
    try:
        _probe_hdmi_now()
        _hdmi_probe_mono = time.monotonic()
    finally:
        with _lock:
            _hdmi_probe_in_flight = False


def _avfoundation_devices() -> list[tuple[int, str, str]]:
    """OpenCV AVFoundation indexes with names. Cached; Swift is slow to start."""
    global _av_devices_cache
    if _av_devices_cache is not None:
        return _av_devices_cache
    if sys.platform != "darwin":
        _av_devices_cache = []
        return _av_devices_cache
    # Same enumeration OpenCV uses: video + muxed, sorted by uniqueID.
    script = (
        "import AVFoundation\n"
        "import Foundation\n"
        "let video = AVCaptureDevice.devices(for: .video)\n"
        "let muxed = AVCaptureDevice.devices(for: .muxed)\n"
        "let all = (video + muxed).sorted { $0.uniqueID < $1.uniqueID }\n"
        "for (i, d) in all.enumerated() {\n"
        '    print("\\(i)\\t\\(d.localizedName)\\t\\(d.deviceType.rawValue)")\n'
        "}\n"
    )
    path = ""
    try:
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".swift", delete=False) as handle:
            handle.write(script)
            path = handle.name
        result = subprocess.run(
            ["swift", path],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        _av_devices_cache = []
        return _av_devices_cache
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
    out: list[tuple[int, str, str]] = []
    for line in (result.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not parts[0].strip().isdigit():
            continue
        idx = int(parts[0].strip())
        name = parts[1].strip()
        dtype = parts[2].strip() if len(parts) > 2 else ""
        if name:
            out.append((idx, name, dtype))
    _av_devices_cache = out
    return _av_devices_cache


def _device_name(index: int) -> str:
    for idx, name, _dtype in _avfoundation_devices():
        if idx == index:
            return name
    return ""


def _candidate_capture_indices() -> list[int]:
    env = str(os.environ.get("PIGEON_HDMI_CAPTURE_INDEX") or "").strip()
    if env.isdigit():
        return [int(env)]
    named = _avfoundation_devices()
    hdmi = [i for i, name, dtype in named if _is_hdmi_camera(name, dtype)]
    if hdmi:
        return hdmi
    other = [i for i, name, dtype in named if not _is_skip_camera(name, dtype)]
    if other:
        return other
    if named:
        return []
    # Do not scan 0..3 on macOS — Continuity Camera often sits at index 1.
    if sys.platform == "darwin":
        return []
    if sys.platform.startswith("linux"):
        # Only USB devices — opening the Pi's SoC codec/ISP nodes fails with
        # V4L2 "can't capture by index" noise and false presence.
        return _linux_usb_video_indices()
    out = [CAPTURE_INDEX]
    for extra in (1, 2, 3):
        if extra not in out:
            out.append(extra)
    return out


def _opencv_backend():
    import cv2

    if sys.platform == "darwin" and hasattr(cv2, "CAP_AVFOUNDATION"):
        return cv2.CAP_AVFOUNDATION
    if sys.platform.startswith("linux") and hasattr(cv2, "CAP_V4L2"):
        return cv2.CAP_V4L2
    return cv2.CAP_ANY


def _open_capture_at(index: int):
    import cv2

    cap = cv2.VideoCapture(index, _opencv_backend())
    if cap is None or not cap.isOpened():
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
        return None
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    cap.set(cv2.CAP_PROP_FOURCC, fourcc)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(PREFERRED_WIDTH))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(PREFERRED_HEIGHT))
    frame = None
    for _ in range(8):
        ok, frame = cap.read()
        if ok and frame is not None and getattr(frame, "size", 0):
            return cap
    try:
        cap.release()
    except Exception:
        pass
    return None


def _grab_frame():
    global _cap, _cap_index, _av_devices_cache
    try:
        import cv2  # noqa: F401
    except ImportError:
        return None
    if _cap is None or not _cap.isOpened():
        _cap = None
        _cap_index = None
        env = str(os.environ.get("PIGEON_HDMI_CAPTURE_INDEX") or "").strip()
        if env.isdigit():
            opened = _open_capture_at(int(env))
            if opened is not None:
                _cap = opened
                _cap_index = int(env)
        else:
            # Prefer the named HDMI dongle (blueAVS). Never open iPhone / FaceTime
            # when a capture card is present — iPhone is also "external" and 1080p.
            for index in _candidate_capture_indices():
                opened = _open_capture_at(index)
                if opened is None:
                    continue
                _cap = opened
                _cap_index = index
                break
        if _cap is None:
            note_hdmi_present(False)
            return None
    ok, frame = _cap.read()
    if not ok or frame is None or not getattr(frame, "size", 0):
        note_hdmi_present(False)
        _drop_open_capture()
        return None
    if not _note_frame_signal(frame):
        # Keep the handle open so a later probe can see the cable return.
        return None
    return frame


def _drop_open_capture() -> None:
    """Close the OpenCV handle without resetting frame-check cadence."""
    global _cap, _cap_index, _av_devices_cache
    cap = _cap
    _cap = None
    _cap_index = None
    _av_devices_cache = None
    if cap is None:
        return
    try:
        cap.release()
    except Exception:
        pass
