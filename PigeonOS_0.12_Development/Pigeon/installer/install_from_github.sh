#!/bin/bash
# Fresh-install Pigeon from GitHub (no Mac required).
#
# Pi / Linux: downloads the official release tarball (or main-branch zip fallback).
# macOS: downloads main-branch zip and runs the Mac installer.
#
# Usage:
#   bash install_from_github.sh
#   bash install_from_github.sh --dir "$HOME/Pigeon_0.7.20"
#   PIGEON_INSTALL_DIR=~/Apps/Pigeon bash install_from_github.sh
set -euo pipefail

REPO="${PIGEON_UPDATE_GITHUB_USER:-jasonhenle}/${PIGEON_UPDATE_GITHUB_REPO:-pigeon_OS_0.12.x_JEH}"
BRANCH="${PIGEON_UPDATE_GITHUB_BRANCH:-main}"
APP_PREFIX="PigeonOS_0.12_Development/Pigeon"
INSTALL_DIR="${PIGEON_INSTALL_DIR:-}"
IN_PLACE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)
      INSTALL_DIR="${2:-}"
      shift 2
      ;;
    --in-place)
      IN_PLACE=1
      shift
      ;;
    -h|--help)
      cat <<EOF
Install Pigeon from GitHub (${REPO}, branch ${BRANCH}).

  bash install_from_github.sh [--dir PATH] [--in-place]

Pi/Linux: prefers GitHub Release tarball (pigeon_*_raspberry_pi.tar.gz).
Fallback: main-branch zip (same source as in-app Updates).

macOS: main-branch zip + installer/install_pigeon.sh

Settings (devices, TMDb key, pairing) stay in ~/.pigeon_0_6 — not overwritten.
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

for cmd in curl python3 tar; do
  command -v "${cmd}" >/dev/null 2>&1 || {
    echo "pigeon: ${cmd} is required." >&2
    exit 1
  }
done

WORKDIR="$(mktemp -d /tmp/pigeon-install.XXXXXX)"
trap 'rm -rf "${WORKDIR}"' EXIT

resolve_release_tarball() {
  python3 - <<PY
import json, urllib.request, sys
repo = "${REPO}"
req = urllib.request.Request(
    f"https://api.github.com/repos/{repo}/releases/latest",
    headers={"User-Agent": "Pigeon/install", "Accept": "application/vnd.github+json"},
)
try:
    with urllib.request.urlopen(req, timeout=25) as resp:
        data = json.load(resp)
except Exception:
    sys.exit(1)
for asset in data.get("assets") or []:
    name = str(asset.get("name") or "")
    if name.startswith("pigeon_") and name.endswith("_raspberry_pi.tar.gz"):
        url = str(asset.get("browser_download_url") or "").strip()
        if url:
            print(url)
            sys.exit(0)
sys.exit(1)
PY
}

install_from_zip() {
  local zip_url="https://codeload.github.com/${REPO}/zip/refs/heads/${BRANCH}"
  echo "==> Downloading ${zip_url}" >&2
  curl -fsSL -o "${WORKDIR}/pigeon.zip" "${zip_url}"
  python3 -X utf8 - <<'PY' "${WORKDIR}/pigeon.zip" "${WORKDIR}/extract" "${APP_PREFIX}" || {
import posixpath
import sys
import zipfile
from pathlib import Path

zip_path, out, app_rel = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
marker = app_rel.rstrip("/") + "/"
out.mkdir(parents=True, exist_ok=True)
root = out.resolve()

# Resource limits. A real Pigeon snapshot is far below these (largest file is
# ~60 MB), so hitting one means a corrupt or hostile archive (e.g. a zip bomb).
MAX_MEMBERS = 100_000
MAX_FILE_BYTES = 1 << 30   # 1 GiB for any single file
MAX_TOTAL_BYTES = 4 << 30  # 4 GiB extracted in total
CHUNK_BYTES = 1 << 20      # stream in 1 MiB chunks; never load a whole file


def safe_target(member_name):
    """Map a ZIP member to a path under root; refuse anything that escapes it
    (``../`` segments, absolute paths, backslash tricks).

    Purely lexical (no filesystem calls), so an unusual character in a file
    name (e.g. macOS's U+202F in screenshot names) cannot crash the check under
    a non-UTF-8 locale. This script only ever writes regular files, so there
    are no symlinks under root to follow."""
    if not member_name or "\\" in member_name or "\x00" in member_name or member_name.startswith("/"):
        return None
    norm = posixpath.normpath(member_name)
    if norm in (".", "..") or norm.startswith("../"):
        return None
    return root / norm


with zipfile.ZipFile(zip_path) as zf:
    # Validate every member before writing anything, so a crafted archive
    # cannot leave a partial extraction behind.
    infos = zf.infolist()
    if len(infos) > MAX_MEMBERS:
        sys.exit(f"install archive has too many entries ({len(infos)})")
    declared_total = 0
    for info in infos:
        if safe_target(info.filename) is None:
            sys.exit(f"unsafe path in install archive: {info.filename!r}")
        if marker in info.filename and not info.is_dir():
            if info.file_size > MAX_FILE_BYTES:
                sys.exit(f"install archive member too large: {info.filename!r}")
            declared_total += info.file_size
    if declared_total > MAX_TOTAL_BYTES:
        sys.exit(f"install archive expands to more than {MAX_TOTAL_BYTES} bytes")
    # Sizes in ZIP headers can lie, so the copy below also counts real bytes.
    written_total = 0
    for info in infos:
        name = info.filename
        if marker not in name:
            continue
        target = safe_target(name)
        if info.is_dir() or name.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        written_file = 0
        with zf.open(info) as src, open(target, "wb") as dst:
            while True:
                chunk = src.read(CHUNK_BYTES)
                if not chunk:
                    break
                written_file += len(chunk)
                written_total += len(chunk)
                if written_file > MAX_FILE_BYTES or written_total > MAX_TOTAL_BYTES:
                    sys.exit(f"install archive exceeds size limits at {name!r}")
                dst.write(chunk)
        mode = (info.external_attr >> 16) & 0o777  # no setuid/setgid/sticky
        if mode:
            target.chmod(mode)
PY
    echo "pigeon: archive extraction failed or was rejected as unsafe." >&2
    exit 1
  }
  local app=""
  for d in "${WORKDIR}/extract"/*/"${APP_PREFIX}"; do
    if [[ -f "${d}/pigeonSystem/pigeon_0_12.py" || -f "${d}/pigeonSystem/pigeon_0_9.py" || -f "${d}/pigeonSystem/pigeon_0_8.py" ]]; then
      app="${d}"
      break
    fi
  done
  if [[ -z "${app}" ]]; then
    echo "pigeon: could not find app folder in GitHub zip." >&2
    exit 1
  fi
  echo "${app}"
}

install_pi_linux() {
  local tarball_url=""
  if tarball_url="$(resolve_release_tarball 2>/dev/null)"; then
    echo "==> Downloading release tarball" >&2
    echo "    ${tarball_url}" >&2
    curl -fsSL -o "${WORKDIR}/pigeon.tar.gz" "${tarball_url}"
    if ! python3 -X utf8 - <<'PY' "${WORKDIR}/pigeon.tar.gz" "${WORKDIR}/release"; then
import posixpath
import sys
import tarfile
from pathlib import Path

tar_path, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
root = out.resolve()

# Resource limits. A real Pigeon snapshot is far below these (largest file is
# ~60 MB), so hitting one means a corrupt or hostile archive (e.g. a zip bomb).
MAX_MEMBERS = 100_000
MAX_FILE_BYTES = 1 << 30   # 1 GiB for any single file
MAX_TOTAL_BYTES = 4 << 30  # 4 GiB extracted in total


def bad_path(name):
    """Absolute, backslash, or any ``..`` segment. Rejecting ``..`` outright
    (rather than resolving it) also closes symlink-then-``..`` escapes."""
    if not name or name.startswith("/") or "\\" in name:
        return True
    return ".." in name.split("/")


with tarfile.open(tar_path, "r:gz") as tf:
    members = tf.getmembers()
    # Validate everything before writing anything.
    if len(members) > MAX_MEMBERS:
        sys.exit(f"release tarball has too many entries ({len(members)})")
    total = sum(m.size for m in members if m.isreg())
    if total > MAX_TOTAL_BYTES or any(m.size > MAX_FILE_BYTES for m in members if m.isreg()):
        sys.exit("release tarball exceeds size limits")
    for m in members:
        if bad_path(m.name):
            sys.exit(f"unsafe path in release tarball: {m.name!r}")
        if not (m.isreg() or m.isdir() or m.issym() or m.islnk()):
            sys.exit(f"unsupported member type in release tarball: {m.name!r}")
        if (m.issym() or m.islnk()) and bad_path(m.linkname):
            sys.exit(f"unsafe link in release tarball: {m.name!r} -> {m.linkname!r}")
        m.mode &= 0o777  # drop setuid/setgid/sticky
        m.uid = m.gid = 0
        m.uname = m.gname = ""
    if hasattr(tarfile, "data_filter"):
        # Python 3.12+ (and security backports): stdlib's own safety filter.
        tf.extractall(root, members=members, filter="data")
    else:
        tf.extractall(root, members=members)
PY
      echo "pigeon: release tarball extraction failed or was rejected as unsafe." >&2
      exit 1
    fi
    local app=""
    for d in "${WORKDIR}/release"/Pigeon_*; do
      if [[ -f "${d}/pigeonSystem/pigeon_0_12.py" || -f "${d}/pigeonSystem/pigeon_0_9.py" || -f "${d}/pigeonSystem/pigeon_0_8.py" ]]; then
        app="${d}"
        break
      fi
    done
    if [[ -n "${app}" ]]; then
      echo "${app}"
      return
    fi
    echo "==> Latest release tarball is not a 0.11 package — falling back to main-branch zip." >&2
  fi

  echo "==> Using main-branch zip (full repo snapshot)." >&2
  install_from_zip
}

OS="$(uname -s)"
if [[ "${OS}" == "Darwin" ]]; then
  APP_SRC="$(install_from_zip)"
  echo "==> Running Mac installer from ${APP_SRC}"
  if [[ -n "${INSTALL_DIR}" ]]; then
    exec bash "${APP_SRC}/installer/install_pigeon.sh" --dir "${INSTALL_DIR}"
  fi
  exec bash "${APP_SRC}/installer/install_pigeon.sh"
fi

if [[ "${OS}" != "Linux" ]]; then
  echo "pigeon: unsupported OS ${OS} — try git clone and manual install." >&2
  exit 1
fi

APP_SRC="$(install_pi_linux)"
echo "==> Installing from ${APP_SRC}"

if [[ "${IN_PLACE}" -eq 1 && -n "${INSTALL_DIR}" ]]; then
  echo "pigeon: --in-place with --dir is ambiguous; use one or the other." >&2
  exit 1
fi

if [[ "${IN_PLACE}" -eq 1 ]]; then
  exec bash "${APP_SRC}/installer/install_on_pi.sh" --in-place
fi

if [[ -n "${INSTALL_DIR}" ]]; then
  exec bash "${APP_SRC}/installer/install_on_pi.sh" --dir "${INSTALL_DIR}"
fi

exec bash "${APP_SRC}/installer/install_on_pi.sh"
