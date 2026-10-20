#!/bin/bash
# Copies the iOS companion app from PigeonOS (PigeonApp/) into the standalone
# pigeon-ios checkout that people build and install, then regenerates its Xcode project.
# PigeonApp/ is the source of truth: change the app there, run this, commit in pigeon-ios.
#
#   tools/sync-pigeon-ios.sh [path/to/pigeon-ios]   (default: ./pigeon-ios)
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
dest="${1:-$root/pigeon-ios}"
[ -d "$dest/.git" ] || { echo "not a git checkout: $dest" >&2; exit 1; }

rsync -a --delete --exclude .DS_Store "$root/PigeonApp/Pigeon/" "$dest/Pigeon/"
rsync -a --delete --exclude .DS_Store "$root/PigeonApp/PigeonTests/" "$dest/PigeonTests/"
cp "$root/PigeonApp/project.yml" "$root/PigeonApp/README.md" "$dest/"
(cd "$dest" && xcodegen generate)
echo "Synced to $dest. Review with: git -C $dest status"
