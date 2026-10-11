"""Compatibility shim: Pigeon's entry point is now ``pigeon_0_12.py``.

Kept so installs whose updater or launcher still looks for ``pigeon_0_11.py``
(0.11.x) keep working across the rename: running this file runs
``pigeon_0_12.py`` as ``__main__``, and importing it re-exports that module.
Safe to delete once every Mac / Pi has updated past the release that renamed
the entry point.
"""

import os
import runpy
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    runpy.run_path(os.path.join(_HERE, "pigeon_0_12.py"), run_name="__main__")
else:
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)
    from pigeon_0_12 import *  # noqa: F401,F403
