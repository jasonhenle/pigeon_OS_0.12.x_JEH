"""Startup must drive Tk exactly as the baseline version did (default: 9cbf40b).

``startup_trace_harness.py`` runs ``main()`` under a fake ``tkinter`` and records,
in order, every widget / window call, ``after()`` delay and callback, binding,
and main-thread thread start. It then runs the scheduled callbacks for two
rounds and fires every bound handler once.

The baseline is commit ``9cbf40b`` (the 251-frame splash, which lifts the
overlay above all shell children). Before that it was 0.11.34 (``30b2be9``),
the last version whose ``bootstrap()`` was a single function. It is
extracted from git into a
temporary folder and traced **on the same machine**, so platform differences
(GPIO / pyatv / fonts present or not) cancel out.

Normalised away, because they vary between two runs of *either* version:

- the version string;
- the ``_playback_ui_tick`` delay (computed from elapsed time);
- what worker threads do (threads they start, ``after()`` callbacks they
  schedule). The harness lists those separately and does not run them;
- the ``pigeon-weather`` fetch thread. Opening settings forces a weather
  refresh, which is skipped while an earlier fetch is still on the network,
  so whether it starts on the main thread depends on network latency.

Skipped when git or the baseline commit is not available (e.g. an installed
copy without history). If a change is *meant* to alter startup, move the
baseline: ``PIGEON_TRACE_BASELINE=<commit>`` (and update ``BASELINE`` below
when that change lands).
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

_SYS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HARNESS = os.path.join(_SYS, "tests", "startup_trace_harness.py")
BASELINE = os.environ.get("PIGEON_TRACE_BASELINE", "9cbf40b")
CONFIGS = {
    "default": [],  # with the extensions loaded this is the splash path
    "no_ext": ["--no-ext"],  # _PIGEON_EXT off: no splash, root.after(1, bootstrap)
    "kiosk": ["--kiosk"],
    "devices": ["--devices"],
}
_COMMON = ["--ticks", "--rounds=2", "--events"]


def normalise(text: str) -> str:
    out, bg = [], False
    for line in text.splitlines():
        if line.startswith("# threads started by other threads"):
            bg = True
            out.append(line)
            continue
        if line.startswith("# "):
            bg = False
        if bg:
            continue
        if line.startswith("thread.start name=pigeon-weather "):
            continue
        line = re.sub(r"\b0\.\d+\.\d+\b", "<version>", line)
        line = re.sub(r"root\.after\(\d+, cb:_playback_ui_tick\)", "root.after(<ms>, cb:_playback_ui_tick)", line)
        out.append(line)
    return "\n".join(out) + "\n"


def trace(config: str, cwd: str = _SYS) -> str:
    with tempfile.TemporaryDirectory() as home, tempfile.NamedTemporaryFile("r", suffix=".txt") as out:
        env = dict(os.environ, HOME=home)
        subprocess.run([sys.executable, _HARNESS, out.name, *CONFIGS[config], *_COMMON], cwd=cwd, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=170, check=True)
        return normalise(open(out.name, encoding="utf-8").read())


def _baseline_tree(dest: str) -> str | None:
    """Extract the baseline's pigeonSystem into ``dest``; None if impossible."""
    git = shutil.which("git")
    if git is None:
        return None
    try:
        top = subprocess.run([git, "rev-parse", "--show-toplevel"], cwd=_SYS, capture_output=True,
                             text=True, check=True).stdout.strip()
        rel = os.path.relpath(_SYS, top)
        subprocess.run([git, "cat-file", "-e", f"{BASELINE}^{{commit}}"], cwd=top, check=True,
                       capture_output=True)
        arch = subprocess.run([git, "archive", BASELINE, rel], cwd=top, capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", dest], input=arch, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    path = os.path.join(dest, rel)
    entry = ("pigeon_0_12.py", "pigeon_0_9.py")  # baselines before the rename have only the old name
    return path if any(os.path.isfile(os.path.join(path, e)) for e in entry) else None


class StartupTraceTests(unittest.TestCase):
    maxDiff = 4000

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = _baseline_tree(cls._tmp.name)
        if cls.base is None:
            cls._tmp.cleanup()
            raise unittest.SkipTest(f"baseline {BASELINE} not available from git")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _check(self, name):
        self.assertEqual(trace(name), trace(name, self.base), f"startup trace '{name}' differs from {BASELINE}")

    def test_default(self):
        self._check("default")

    def test_no_ext(self):
        self._check("no_ext")

    def test_kiosk(self):
        self._check("kiosk")

    def test_saved_devices(self):
        self._check("devices")


if __name__ == "__main__":
    unittest.main()
