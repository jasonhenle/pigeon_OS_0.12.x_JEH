"""Record everything startup does to Tk, for comparing two versions.

Usage (from ``pigeonSystem``)::

    HOME=$(mktemp -d) python3 tests/startup_trace_harness.py OUT.txt [--no-ext] [--kiosk]
        [--devices] [--ticks] [--rounds=N] [--events]

Runs ``main()`` under a fake ``tkinter`` (like ``smoke_bootstrap.py``) and
writes one normalised line per event, in order:

- every call on the ``tkinter`` module mock and its children (widget
  construction, ``pack`` / ``place`` / ``configure`` / ``bind`` ...);
- every call on the root window (``after`` delays, ``bind_all``, ``protocol``,
  ``update`` ...), with callbacks named by ``__name__``;
- every ``threading.Thread`` start (thread name and target);
- the callbacks bootstrap() scheduled, run once each with ``--ticks``.

Object ids, timings and numpy contents are normalised away, so two runs of the
same code produce the same file and a diff between versions shows real
changes in order, delays, arguments or callbacks. ``--no-ext`` forces
``_PIGEON_EXT = False`` (the path used when optional imports fail).
"""
import functools
import os
import re
import sys
import threading
from unittest import mock

OUT = sys.argv[1]
NO_EXT = "--no-ext" in sys.argv
TICKS = "--ticks" in sys.argv
ROUNDS = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--rounds=")), "1"))
EVENTS = "--events" in sys.argv
KIOSK = "--kiosk" in sys.argv
DEVICES = "--devices" in sys.argv
sys.path.insert(0, os.getcwd())
for m in ["tkinter", "tkinter.font", "tkinter.messagebox", "tkinter.scrolledtext", "tkinter.simpledialog",
          "tkinter.ttk", "PIL.ImageTk"]:
    sys.modules[m] = mock.MagicMock(name=m)
import tkinter  # noqa: E402

events = []
lock = threading.Lock()
_ID = re.compile(r"0x[0-9a-fA-F]+|id=\\?'\d+\\?'|\bat \d+\b")
_NUM = re.compile(r"\d+\.\d{3,}")


def norm(v, depth=0):
    if depth > 3:
        return "…"
    if isinstance(v, mock.Mock):
        return "<" + (v._extract_mock_name() or "mock") + ">"
    # a nested def (old) and a bind_deps partial of the lifted helper (new) are
    # the same callback: name them alike
    if isinstance(v, functools.partial):
        return "cb:" + getattr(v, "__name__", getattr(v.func, "__name__", "?"))
    if callable(v) and hasattr(v, "__name__") and not isinstance(v, type):
        return "cb:" + v.__name__
    if type(v).__name__ == "ndarray":
        return f"ndarray{tuple(v.shape)}:{v.dtype}"
    if isinstance(v, (list, tuple)):
        inner = ", ".join(norm(x, depth + 1) for x in list(v)[:12])
        return ("[" + inner + "]") if isinstance(v, list) else ("(" + inner + ")")
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {norm(x, depth + 1)}" for k, x in list(v.items())[:12]) + "}"
    if isinstance(v, float):
        return "<float>"
    r = repr(v)
    r = _ID.sub("#", r)
    r = _NUM.sub("<n>", r)
    return r[:160]


def fmt_call(prefix, name, args, kwargs):
    a = [norm(x) for x in args] + [f"{k}={norm(x)}" for k, x in sorted(kwargs.items())]
    return f"{prefix}{name}({', '.join(a)})"


scheduled = []
boot_calls = []


def make_root(*a, **k):
    r = mock.MagicMock(name="root")
    r.winfo_screenwidth.return_value = 1280
    r.winfo_screenheight.return_value = 800
    r.winfo_width.return_value = 1280
    r.winfo_height.return_value = 800

    def after(ms, fn=None, *args):
        # after() from a worker thread (a poll or scan finishing) races the main
        # thread in any version: list those separately, and mark their ticks
        main_t = threading.current_thread() is threading.main_thread()
        with lock:
            (events if main_t else bg_afters).append(fmt_call("root.", "after", (ms, fn) + args, {}))
        if fn is not None and getattr(fn, "__name__", "") in ("bootstrap", "_bootstrap_after_splash"):
            boot_calls.append(fn)
        elif fn is not None:
            scheduled.append((fn, args, main_t))
        return "after#1"

    r.after.side_effect = after
    r.after_idle.side_effect = lambda fn=None, *args: after("idle", fn, *args)

    def mainloop():
        fn = boot_calls[0]
        if fn.__name__ != "bootstrap":
            fn = fn.keywords["bootstrap"] if isinstance(fn, functools.partial) else dict(
                zip(fn.__code__.co_freevars, fn.__closure__))["bootstrap"].cell_contents
        events.append("== bootstrap() ==")
        fn()
        events.append("== bootstrap returned ==")
        if TICKS:
            # Run what bootstrap() scheduled, then what those callbacks
            # rescheduled, for ROUNDS rounds (one run per callback name per round).
            queue_ = list(scheduled)
            for rnd in range(ROUNDS):
                del scheduled[:]
                seen = set()
                for cb, cargs, main_t in queue_:
                    nm = getattr(cb, "__name__", repr(cb))
                    if not main_t:
                        bg_afters.append(f"tick {nm}")
                        continue  # racy arrival: not run, so it cannot reorder the trace
                    if nm in seen:
                        continue
                    seen.add(nm)
                    events.append(f"== round {rnd} tick {nm} ==")
                    try:
                        cb(*cargs)
                    except BaseException as e:  # noqa: BLE001
                        events.append(f"tick-error {nm}: {type(e).__name__}: {norm(str(e))[:80]}")
                queue_ = list(scheduled)
        if EVENTS:
            # Fire every handler bound with bind / bind_all / bind_class / command=
            # once, with a fake event, in registration order.
            fired = set()
            calls = [("root", c) for rr in roots for c in rr.mock_calls] + [("tk", c) for c in tkinter.mock_calls]
            for src, (name, args, kwargs) in calls:
                leaf = name.rsplit(".", 1)[-1]
                cbs = []
                if leaf in ("bind", "bind_all", "bind_class", "tag_bind"):
                    cbs = [(str(args[-2]) if len(args) >= 2 else "?", a) for a in args if callable(a) and not isinstance(a, mock.Mock)]
                cbs += [("command", v) for k, v in kwargs.items() if k == "command" and callable(v) and not isinstance(v, mock.Mock)]
                for seq, cb in cbs:
                    key = (getattr(cb, "__name__", "?"), seq)
                    if key in fired:
                        continue
                    fired.add(key)
                    ev = mock.MagicMock(name="event")
                    ev.keysym = "Tab"
                    ev.char = ""
                    ev.state = 0
                    ev.delta = 0
                    events.append(f"== fire {key[0]} {seq} ==")
                    try:
                        try:
                            cb(ev)
                        except TypeError as e:
                            if "positional argument" in str(e):
                                cb()
                            else:
                                raise
                    except BaseException as e:  # noqa: BLE001
                        events.append(f"fire-error {key[0]}: {type(e).__name__}: {norm(str(e))[:80]}")

    r.mainloop.side_effect = mainloop
    roots.append(r)
    return r


roots = []
tkinter.Tk = make_root
# (There is no switch that turns the splash off by itself: with the extensions
# loaded startup always takes the splash path; --no-ext takes the other one.)

_orig_start = threading.Thread.start


bg_starts = []
bg_afters = []


def _start(self):
    tgt = getattr(self, "_target", None)
    line = f"thread.start name={self.name} target={norm(tgt)}"
    with lock:
        # starts from the main thread are ordered; starts from worker threads
        # race by nature, so they are listed (sorted) separately
        (events if threading.current_thread() is threading.main_thread() else bg_starts).append(line)
    return _orig_start(self)


threading.Thread.start = _start

if KIOSK:
    # Pretend to be the Pi kiosk; the window-manager calls become recorded no-ops.
    import pigeon.linux_kiosk as _lk

    _lk.linux_kiosk_enabled = lambda: True
    for _fn in ("enforce_kiosk", "release_kiosk", "schedule_kiosk_guard", "apply_kiosk_fullscreen"):
        setattr(_lk, _fn, (lambda nm: (lambda *a, **k: events.append(f"kiosk.{nm}") or []))(_fn))
    _lk.window_covers_display = lambda *a, **k: True
if DEVICES:
    # Saved player + AV receiver on addresses that refuse connections at once.
    from pigeon import app_state as _as

    _as.write_saved_streaming_device({"role": "streaming", "kind": "apple_tv", "name": "Living Room",
                                      "address": "127.0.0.1", "identifier": "TEST-ATV"})
    _as.write_saved_av_receiver({"role": "av", "kind": "denon", "name": "AVR", "address": "127.0.0.1"})
    _as.write_last_receiver(host="127.0.0.1", name="AVR")
    _as.write_last_apple_tv(identifier="TEST-ATV", address="127.0.0.1", name="Living Room")

# The entry point is named after the version (pigeon_0_12.py); baselines older
# than the rename (e.g. 0.11.34) only have pigeon_0_9.py.
try:
    import pigeon_0_12 as pigeon_app  # noqa: E402
except ImportError:
    import pigeon_0_9 as pigeon_app  # noqa: E402

if NO_EXT:
    pigeon_app._PIGEON_EXT = False
sys.argv = [os.path.basename(pigeon_app.__file__)]


def watchdog():
    import time
    time.sleep(150)
    os._exit(3)


threading.Thread(target=watchdog, daemon=True).start()
try:
    rc = pigeon_app.main()
    events.append(f"main returned {rc}")
except BaseException as e:  # noqa: BLE001
    events.append(f"main raised {type(e).__name__}: {e}")

# the tkinter module mock recorded every widget and method call, in order
tk_lines = []
for c in tkinter.mock_calls:
    name, args, kwargs = c
    tk_lines.append(fmt_call("tk.", name, args, kwargs))
root_lines = []
for r in roots:
    for c in r.mock_calls:
        name, args, kwargs = c
        if name in ("after", "after_idle"):
            continue  # already in events, in order
        root_lines.append(fmt_call("root.", name, args, kwargs))
with open(OUT, "w") as f:
    f.write("# events (after / threads / phases), in order\n")
    f.write("\n".join(e for e in events if not e.startswith("thread.start name=Thread-")) + "\n")
    f.write("# threads started by other threads, after() from other threads (unordered)\n")
    f.write("\n".join(sorted(bg_starts + bg_afters)) + "\n")
    f.write("# root window calls, in order\n")
    f.write("\n".join(root_lines) + "\n")
    f.write("# tkinter calls, in order\n")
    f.write("\n".join(tk_lines) + "\n")
print(len(events), "events;", len(root_lines), "root calls;", len(tk_lines), "tk calls", flush=True)
os._exit(0)
