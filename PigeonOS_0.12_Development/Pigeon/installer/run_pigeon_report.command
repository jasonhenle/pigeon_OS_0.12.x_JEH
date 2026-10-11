#!/bin/bash
# Pigeon accuracy report (Mac only): collects TMDb events from every Pigeon
# (pi4, pi5, this Mac) and opens the Live / Gallery / Log page in the browser.
# Spreadsheet: ~/Pigeon/pigeonReport/pigeon_accuracy.csv (+ .numbers on export).
set -euo pipefail

INSTALLER_DIR="$(cd "$(dirname "$0")" && pwd)"
SYSTEM_DIR="$(cd "${INSTALLER_DIR}/../pigeonSystem" && pwd)"
PY="${SYSTEM_DIR}/.venv/bin/python"
[[ -x "${PY}" ]] || PY="$(command -v python3)"
cd "${SYSTEM_DIR}"
exec "${PY}" pigeon_report_server.py "$@"
