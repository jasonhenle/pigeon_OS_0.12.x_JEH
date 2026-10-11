#!/bin/bash
# Legacy 0.10 name — exec the 0.11 launcher.
set -euo pipefail
exec "$(cd "$(dirname "$0")" && pwd)/run_pigeon_0_12.sh" "$@"
