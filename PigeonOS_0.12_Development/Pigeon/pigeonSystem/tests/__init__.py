# Rotary / ADB reliability tests for pigeon.rotary_serial
"""Test package setup.

State is isolated. Many modules read and write ``state.json``, ``fullscreen_viz.json`` and
friends under ``pigeon_state_dir()``; without this the suite reads (and, via background
saves such as the remembered visualizer preset, writes) the developer's real
``~/.pigeon_0_6``, making results depend on the machine and on previous runs. The run
gets a throwaway ``PIGEON_STATE_DIR`` instead. Individual tests may still point
``state_file`` / ``config_path`` somewhere more specific.

Weather is isolated for the whole run. ``ensure_weather()`` (reached from the clock saver
and the now-playing weather zones) otherwise starts a real network fetch on a background
thread whose result lands at an arbitrary moment, changing layouts mid-test. The cache is
seeded with fixed temperatures and no fetch thread is ever started; tests that exercise
the cache itself (``WeatherCacheTests``) call ``pigeon.weather`` internals directly and
are unaffected.
"""

from __future__ import annotations

import atexit as _atexit
import os as _os
import shutil as _shutil
import sys as _sys
import tempfile as _tempfile
from unittest import mock as _mock

# Must run before anything calls ``pigeon.runtime_paths.pigeon_state_dir()`` (it caches).
_STATE_DIR = _tempfile.mkdtemp(prefix="pigeon-test-state-")
_os.environ["PIGEON_STATE_DIR"] = _STATE_DIR
_atexit.register(_shutil.rmtree, _STATE_DIR, ignore_errors=True)

_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

from pigeon import runtime_paths as _rp  # noqa: E402

_rp._CACHED = None  # in case something resolved the real directory before this package loaded

from pigeon import weather as _wx  # noqa: E402

TEST_WEATHER = _wx.WeatherTemps(high_f=80, low_f=60, zip_code="00000")


def reseed_test_weather() -> None:
    """Put the fixed temperatures back in the weather cache."""
    _wx._store(TEST_WEATHER)


_mock.patch.object(_wx, "refresh_weather", return_value=False).start()
reseed_test_weather()
