"""Run main() with a fake tkinter so bootstrap()'s top level executes once."""
import sys, os, threading, traceback, builtins, functools
from unittest import mock
sys.path.insert(0, os.getcwd())
for m in ["tkinter","tkinter.font","tkinter.messagebox","tkinter.scrolledtext","tkinter.simpledialog","tkinter.ttk","PIL.ImageTk"]:
    sys.modules[m] = mock.MagicMock(name=m)
import tkinter
reached = {"boot": False}
scheduled = []
class FakeTk(mock.MagicMock):
    pass
def make_root(*a, **k):
    r = mock.MagicMock(name="root")
    r.winfo_screenwidth.return_value = 1280
    r.winfo_screenheight.return_value = 800
    r.winfo_width.return_value = 1280
    r.winfo_height.return_value = 800
    calls = []
    def after(ms, fn=None, *args):
        if fn is not None and getattr(fn, "__name__", "") in ("bootstrap", "_bootstrap_after_splash"):
            calls.append(fn)
        elif fn is not None:
            scheduled.append((fn, args))
        return "after#1"
    r.after.side_effect = after
    r.after_idle.side_effect = lambda fn=None, *a: after(0, fn)
    def mainloop():
        fn = calls[0]
        if fn.__name__ != "bootstrap":
            if isinstance(fn, functools.partial):  # lifted in pass 12 (bind_deps)
                fn = fn.keywords["bootstrap"]
            else:
                cells = dict(zip(fn.__code__.co_freevars, fn.__closure__))
                fn = cells["bootstrap"].cell_contents
        print("SMOKE: running bootstrap", flush=True)
        fn()
        print("SMOKE: bootstrap returned", flush=True)
        if os.environ.get("SMOKE_TICKS"):
            # Run every callback bootstrap() scheduled, once, and report the errors.
            # Mocked Tk makes many fail for boring reasons; compare runs to spot new ones.
            seen = set()
            for cb, cargs in list(scheduled):
                nm = getattr(cb, "__name__", repr(cb))
                if nm in seen:
                    continue
                seen.add(nm)
                try:
                    cb(*cargs)
                    print(f"TICK ok {nm}", flush=True)
                except BaseException as e:
                    print(f"TICK err {nm}: {type(e).__name__}: {str(e)[:120]}", flush=True)
    r.mainloop.side_effect = mainloop
    return r
tkinter.Tk = make_root
# Note: Pigeon has no PIGEON_NO_SPLASH switch; with the extensions loaded this always
# runs the splash path. tests/startup_trace_harness.py --no-ext covers the other path.
import pigeon_0_12
sys.argv = ["pigeon_0_12.py"]
def watchdog():
    import time; time.sleep(150); print("SMOKE: timeout", flush=True); os._exit(3)
threading.Thread(target=watchdog, daemon=True).start()
try:
    rc = pigeon_0_12.main()
    print("SMOKE: main returned", rc, flush=True)
except SystemExit as e:
    print("SMOKE: exit", e, flush=True)
except BaseException:
    traceback.print_exc()
    print("SMOKE: exception", flush=True)
os._exit(0)
