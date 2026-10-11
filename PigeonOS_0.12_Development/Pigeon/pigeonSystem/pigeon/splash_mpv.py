"""Play the opaque part of the splash in mpv, embedded in the Tk splash overlay.

Tk has to copy every full-window frame through ``PhotoImage.paste``, which costs
more than a 30 fps frame on the Pi. mpv decodes and draws on its own threads and
the GPU, so the Python UI thread does nothing per frame and bootstrap can run
while the splash plays.

The video (built by ``pigeon.tools_build_splash_video``) holds PNG frames
``0..SPLASH_CLOCK_REVEAL_FRAME`` flattened over black. mpv renders into a Tk child
window (``--wid``), which keeps it inside Pigeon's override-redirect, topmost
kiosk window. Playback stops on the logo-hold frame (``--end`` + keep-open) until
bootstrap finishes, then resumes and holds the last frame; Tk paints that same
reveal frame underneath and plays the see-through outro from there.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

# Relative to the app root (the folder holding ``pigeonAssets``). Kept outside the
# ``pigeonSplash`` folder so ``find_splash_video_path`` never picks it up as a full splash.
SPLASH_MPV_VIDEO_RELPATH = "pigeonAssets/pigeonSplashVideo/pigeon_splash_opaque.mp4"

# How long to wait for mpv to open its video output before falling back to Tk.
_READY_TIMEOUT_S = 3.0


def _log(msg: str) -> None:
    try:
        sys.stderr.write(f"pigeon: splash mpv {msg}\n")
        sys.stderr.flush()
    except Exception:
        pass


def splash_mpv_enabled() -> bool:
    """On by default on Linux (the Pi); ``PIGEON_SPLASH_MPV=0`` / ``1`` overrides.

    ``--wid`` embedding needs an X11 window id, so macOS stays on the Tk path.
    """
    env = os.environ.get("PIGEON_SPLASH_MPV", "").strip().lower()
    if env in ("0", "false", "no", "off"):
        return False
    if env in ("1", "true", "yes", "on"):
        return True
    return sys.platform.startswith("linux")


def splash_mpv_video_path(project_dir: Path) -> Path | None:
    p = Path(project_dir) / SPLASH_MPV_VIDEO_RELPATH
    return p if p.is_file() else None


def mpv_command(
    video: Path,
    *,
    wid: int,
    ipc_path: str,
    hold_end_s: float,
    platform: str = sys.platform,
) -> list[str]:
    cmd = [
        shutil.which("mpv") or "mpv",
        "--no-config",
        "--input-terminal=no",
        "--msg-level=all=error",
        f"--wid={int(wid)}",
        f"--input-ipc-server={ipc_path}",
        "--no-audio",
        "--keep-open=yes",
        "--keep-open-pause=yes",
        f"--end={hold_end_s:.4f}",
        "--hr-seek=yes",
        "--hwdec=auto-safe",
        "--no-osc",
        "--osd-level=0",
        "--no-input-default-bindings",
        "--input-vo-keyboard=no",
        "--input-cursor=no",
        "--cursor-autohide=always",
    ]
    if platform.startswith("linux"):
        # Tk is an Xwayland client under labwc; --wid needs mpv on X11 too.
        cmd.append("--gpu-context=x11egl")
    extra = os.environ.get("PIGEON_SPLASH_MPV_ARGS", "").split()
    return cmd + extra + ["--", str(video)]


class SplashMpv:
    """One mpv process playing the opaque splash into a Tk window id.

    ``done`` turns true once the last frame is on screen (or mpv died); the Tk
    side polls it from ``after`` because Tk must stay on the main thread.
    """

    def __init__(
        self,
        video: Path,
        *,
        wid: int,
        fps: float,
        hold_frame: int,
        last_frame: int,
        bootstrap_done: list[bool],
    ) -> None:
        self.video = Path(video)
        self.wid = int(wid)
        self.fps = float(fps)
        self.hold_frame = int(hold_frame)
        self.last_frame = int(last_frame)
        self.bootstrap_done = bootstrap_done
        self.ended = False
        self.failed = False
        self._proc: subprocess.Popen | None = None
        self._sock: socket.socket | None = None
        self._buf = b""
        self._req = 0
        self._ipc_path = f"/tmp/pigeon-splash-mpv-{os.getpid()}.sock"

    @property
    def done(self) -> bool:
        return self.ended or self.failed

    # -- startup (main thread) ---------------------------------------------

    def start(self) -> bool:
        """Launch mpv and wait until its video output is up. False → use Tk."""
        try:
            os.unlink(self._ipc_path)
        except OSError:
            pass
        hold_end_s = (self.hold_frame + 0.5) / self.fps
        cmd = mpv_command(self.video, wid=self.wid, ipc_path=self._ipc_path, hold_end_s=hold_end_s)
        t0 = time.monotonic()
        try:
            self._proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )
        except OSError as e:
            _log(f"launch failed: {e}")
            return False
        deadline = t0 + _READY_TIMEOUT_S
        if not self._connect(deadline) or not self._wait_vo(deadline):
            err = self._kill_and_read_stderr()
            _log(f"not ready after {time.monotonic() - t0:.3f}s; using Tk splash. {err}".rstrip())
            return False
        self._sock.settimeout(0.02)
        _log(f"playing (ready in {time.monotonic() - t0:.3f}s)")
        threading.Thread(target=self._watch, name="pigeon-splash-mpv", daemon=True).start()
        return True

    def _connect(self, deadline: float) -> bool:
        while time.monotonic() < deadline:
            if self._proc is None or self._proc.poll() is not None:
                return False
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.connect(self._ipc_path)
            except OSError:
                s.close()
                time.sleep(0.02)
                continue
            self._sock = s
            return True
        return False

    def _wait_vo(self, deadline: float) -> bool:
        while time.monotonic() < deadline:
            if self._proc is None or self._proc.poll() is not None:
                return False
            try:
                if self._get("vo-configured", timeout=0.25) is True:
                    return True
            except OSError:
                return False
            time.sleep(0.02)
        return False

    # -- IPC ---------------------------------------------------------------

    def _send(self, *args: object) -> int:
        self._req += 1
        line = json.dumps({"command": list(args), "request_id": self._req}) + "\n"
        assert self._sock is not None
        self._sock.sendall(line.encode())
        return self._req

    def _read_msgs(self, timeout: float) -> list[dict]:
        assert self._sock is not None
        self._sock.settimeout(timeout)
        try:
            chunk = self._sock.recv(65536)
        except socket.timeout:
            return []
        if not chunk:
            raise OSError("mpv closed IPC")
        self._buf += chunk
        out = []
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def _call(self, *args: object, timeout: float = 0.5) -> dict | None:
        rid = self._send(*args)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for msg in self._read_msgs(max(0.001, end - time.monotonic())):
                if msg.get("request_id") == rid:
                    return msg
        return None

    def _get(self, prop: str, timeout: float = 0.5) -> object:
        r = self._call("get_property", prop, timeout=timeout)
        return None if r is None or r.get("error") != "success" else r.get("data")

    # -- watcher thread ----------------------------------------------------

    def _watch(self) -> None:
        released = False
        resumes = 0
        hold_since: float | None = None
        resume_s = (self.hold_frame + 1) / self.fps
        # Anything past the midpoint between the hold and the last frame is the real end.
        end_threshold_s = (self.hold_frame + self.last_frame) / 2.0 / self.fps
        try:
            while True:
                if self._proc is None or self._proc.poll() is not None:
                    raise OSError("mpv exited")
                eof = self._get("eof-reached") is True
                if not released:
                    if eof and hold_since is None:
                        hold_since = time.monotonic()
                        _log(f"hold frame={self.hold_frame}")
                    if self.bootstrap_done[0]:
                        released = True
                        self._call("set_property", "end", "none")
                        if hold_since is not None:
                            _log(f"hold released after {time.monotonic() - hold_since:.3f}s")
                        # Re-read: the hold may have landed between the read and the release.
                        eof = self._get("eof-reached") is True
                if released and eof:
                    pos = self._get("time-pos")
                    if isinstance(pos, (int, float)) and pos < end_threshold_s:
                        # Parked on the logo hold: step past it and play on. Repeated
                        # parks mean this mpv ignored the ``end`` change; give up.
                        resumes += 1
                        if resumes > 3:
                            raise OSError("could not resume past the logo hold")
                        self._call("seek", resume_s, "absolute+exact")
                        self._call("set_property", "pause", False)
                    else:
                        self.ended = True
                        _log("last frame on screen")
                        return
                time.sleep(0.016)
        except Exception as e:
            if not self.ended:
                self.failed = True
                _log(f"stopped early: {e}")

    # -- teardown ----------------------------------------------------------

    def stop(self) -> None:
        """Quit mpv without blocking the Tk thread."""
        proc = self._proc

        def _reap() -> None:
            try:
                if self._sock is not None:
                    try:
                        self._sock.sendall(b'{"command":["quit"]}\n')
                    except OSError:
                        pass
                if proc is not None:
                    try:
                        proc.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=1.0)
            except Exception:
                pass
            finally:
                try:
                    if self._sock is not None:
                        self._sock.close()
                except OSError:
                    pass
                try:
                    os.unlink(self._ipc_path)
                except OSError:
                    pass

        threading.Thread(target=_reap, name="pigeon-splash-mpv-stop", daemon=True).start()

    def _kill_and_read_stderr(self) -> str:
        proc = self._proc
        if proc is None:
            return ""
        try:
            if proc.poll() is None:
                proc.kill()
            _, err = proc.communicate(timeout=1.0)
            tail = (err or b"").decode(errors="replace").strip().splitlines()[-3:]
            return " | ".join(tail)
        except Exception:
            return ""
        finally:
            try:
                if self._sock is not None:
                    self._sock.close()
            except OSError:
                pass
            try:
                os.unlink(self._ipc_path)
            except OSError:
                pass
