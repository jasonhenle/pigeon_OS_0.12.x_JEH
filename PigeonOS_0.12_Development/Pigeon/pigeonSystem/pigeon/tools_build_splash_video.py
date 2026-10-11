"""Encode the opaque part of the splash PNG sequence to H.264 for mpv playback.

Frames ``0..SPLASH_CLOCK_REVEAL_FRAME`` are flattened over black (exactly what the Tk
path shows before the reveal) and written to ``SPLASH_MPV_VIDEO_RELPATH``. Frame ``i``
of the video is PNG frame ``i``; the last video frame is the reveal frame, where Tk
takes over for the see-through outro.

Run from ``pigeonSystem`` after the splash PNGs change::

    python3 -m pigeon.tools_build_splash_video [--ffmpeg /path/to/ffmpeg]

``ffmpeg`` comes from ``--ffmpeg``, ``PATH``, or the ``imageio-ffmpeg`` package.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

from pigeon.splash_mpv import SPLASH_MPV_VIDEO_RELPATH
from pigeon.splash_sequence import (
    SPLASH_CLOCK_REVEAL_FRAME,
    SPLASH_FPS,
    SPLASH_HOLD_LOGO_FRAME,
    SPLASH_NOMINAL_H,
    SPLASH_NOMINAL_W,
    list_splash_png_paths,
    load_splash_bgra,
)


def _find_ffmpeg(explicit: str | None) -> str:
    if explicit:
        return explicit
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("ffmpeg not found: pass --ffmpeg, install ffmpeg, or pip install imageio-ffmpeg")


def _flatten_over_black(bgra: np.ndarray) -> np.ndarray:
    a = bgra[:, :, 3:4].astype(np.uint16)
    return ((bgra[:, :, :3].astype(np.uint16) * a + 127) // 255).astype(np.uint8)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ffmpeg", help="ffmpeg executable")
    ap.add_argument("--crf", type=int, default=14, help="x264 quality (lower = better)")
    args = ap.parse_args(argv)

    project = Path(__file__).resolve().parents[2]
    assets = project / "pigeonAssets"
    pngs = list_splash_png_paths(assets)
    last = int(SPLASH_CLOCK_REVEAL_FRAME)
    if len(pngs) <= last:
        sys.exit(f"need at least {last + 1} splash PNGs, found {len(pngs)}")
    out = project / SPLASH_MPV_VIDEO_RELPATH
    out.parent.mkdir(parents=True, exist_ok=True)

    w, h = SPLASH_NOMINAL_W, SPLASH_NOMINAL_H
    # Keyframe right after the logo hold so mpv's release seek is a cheap exact seek.
    resume = int(SPLASH_HOLD_LOGO_FRAME) + 1
    cmd = [
        _find_ffmpeg(args.ffmpeg), "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(SPLASH_FPS),
        "-i", "-",
        "-an", "-c:v", "libx264", "-preset", "slow", "-crf", str(args.crf),
        "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        "-color_range", "tv",
        "-g", str(SPLASH_FPS), "-force_key_frames", f"expr:eq(n,{resume})",
        "-movflags", "+faststart",
        str(out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    for i in range(last + 1):
        bgra = load_splash_bgra(pngs[i])
        if bgra is None:
            sys.exit(f"could not read {pngs[i]}")
        if bgra.shape[1] != w or bgra.shape[0] != h:
            bgra = cv2.resize(bgra, (w, h), interpolation=cv2.INTER_AREA)
        proc.stdin.write(np.ascontiguousarray(_flatten_over_black(bgra)).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        return 1
    print(f"wrote {out} ({last + 1} frames, {out.stat().st_size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
