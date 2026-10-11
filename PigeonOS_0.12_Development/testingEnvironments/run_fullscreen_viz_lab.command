#!/bin/bash
# Fullscreen visualizer lab. Extra args pass through, e.g.:
#   run_fullscreen_viz_lab.command --audio ~/Music/song.m4a
#   run_fullscreen_viz_lab.command --bench
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SYS_DIR="$(cd "$SCRIPT_DIR/../Pigeon/pigeonSystem" && pwd)"

if [[ ! -d "${SYS_DIR}/.venv" ]]; then
  python3 -m venv "${SYS_DIR}/.venv"
  "${SYS_DIR}/.venv/bin/python" -m pip install --upgrade pip >/dev/null
  "${SYS_DIR}/.venv/bin/python" -m pip install -r "${SYS_DIR}/requirements.txt"
fi

PY="${SYS_DIR}/.venv/bin/python3"
[[ -x "$PY" ]] || PY="${SYS_DIR}/.venv/bin/python"

exec "$PY" "$SCRIPT_DIR/fullscreen_viz_lab.py" "$@"
