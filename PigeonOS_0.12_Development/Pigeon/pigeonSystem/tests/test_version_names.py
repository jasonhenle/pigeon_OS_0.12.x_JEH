"""File names that carry the version must follow ``pigeon/version.py``.

The entry point is ``pigeon_<MAJOR>_<MINOR>.py`` and its launchers are
``installer/run_pigeon_<MAJOR>_<MINOR>.sh`` / ``.command``. When MINOR is
bumped (0.11 -> 0.12), this test fails until they are renamed and every
reference follows. Older ``pigeon_0_*.py`` files may stay only as compatibility
shims that run the current entry point (installed updaters look for them).
"""

import ast
import glob
import os
import re
import unittest

from pigeon.version import MAJOR, MINOR

_SYS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = os.path.dirname(_SYS)
ENTRY = f"pigeon_{MAJOR}_{MINOR}.py"
TAG = f"{MAJOR}_{MINOR}"


def _read(*parts):
    return open(os.path.join(*parts), encoding="utf-8").read()


class VersionNamedFilesTests(unittest.TestCase):
    def test_entry_point_is_named_after_the_version(self):
        self.assertTrue(os.path.isfile(os.path.join(_SYS, ENTRY)), f"expected pigeonSystem/{ENTRY}")

    def test_launchers_are_named_after_the_version_and_run_the_entry_point(self):
        for ext in ("sh", "command"):
            path = os.path.join(_APP, "installer", f"run_pigeon_{TAG}.{ext}")
            self.assertTrue(os.path.isfile(path), path)
            self.assertIn(f'MAIN_PY="${{SYSTEM_DIR}}/{ENTRY}"', _read(path), path)

    def test_updater_and_packager_know_the_entry_point(self):
        src = _read(_SYS, "pigeon", "github_update.py")
        names = ast.literal_eval(re.search(r"_MAIN_PY_NAMES = (\([^)]*\))", src).group(1))
        self.assertEqual(names[0], ENTRY, "github_update._MAIN_PY_NAMES must list the current entry point first")
        self.assertIn(f"pigeonSystem/{ENTRY}", _read(_APP, "raspberryPi", "package_for_pi.sh"))
        for script in ("pigeon_github_update.sh", "pi_update_from_github.sh", "install_from_github.sh"):
            self.assertIn(f"pigeonSystem/{ENTRY}", _read(_APP, "installer", script), script)

    def test_older_entry_points_are_only_shims(self):
        for path in glob.glob(os.path.join(_SYS, "pigeon_[0-9]*_[0-9]*.py")):
            name = os.path.basename(path)
            if name == ENTRY:
                continue
            src = _read(path)
            self.assertLess(len(src.splitlines()), 40, f"{name} should be a small shim, not a copy of the app")
            self.assertIn(f'"{ENTRY}"', src, f"{name} must run {ENTRY}")

    def test_code_does_not_import_an_old_entry_point(self):
        # The shim and the updater's fallback list aside, nothing should import or name
        # an older entry-point *file*. (``~/.pigeon_0_6`` is the data folder: not a
        # version name, and must never be renamed.)
        old = re.compile(r"\bpigeon_%d_(?!%d\b)\d+\.py\b|\b(?:import|from) pigeon_%d_(?!%d\b)\d+\b"
                         % (MAJOR, MINOR, MAJOR, MINOR))
        allowed = {"github_update.py", "test_version_names.py", "startup_trace_harness.py",
                   "test_startup_trace.py"}
        for path in glob.glob(os.path.join(_SYS, "**", "*.py"), recursive=True):
            name = os.path.basename(path)
            if "__pycache__" in path or name in allowed or re.fullmatch(r"pigeon_\d+_\d+\.py", name):
                continue
            hits = [i for i, line in enumerate(_read(path).splitlines(), 1) if old.search(line)]
            self.assertEqual(hits, [], f"{os.path.relpath(path, _SYS)} mentions an old entry point")


if __name__ == "__main__":
    unittest.main()
