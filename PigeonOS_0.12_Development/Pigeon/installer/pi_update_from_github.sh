#!/bin/bash
# Update Pigeon on Raspberry Pi from GitHub without the in-app updater.
# Use when Updates fails with a latin-1 / U+202F encoding error (bad pasted token).
#
# Usage:
#   bash installer/pi_update_from_github.sh
#   bash installer/pi_update_from_github.sh /home/pi/Pigeon_0.7.16
#
# Requires: curl, unzip or python3, rsync (install via apt if missing).
set -euo pipefail

REPO="${PIGEON_UPDATE_GITHUB_USER:-jasonhenle}/${PIGEON_UPDATE_GITHUB_REPO:-pigeon_OS_0.12.x_JEH}"
BRANCH="${PIGEON_UPDATE_GITHUB_BRANCH:-main}"
ZIP_URL="https://codeload.github.com/${REPO}/zip/refs/heads/${BRANCH}"
APP_REL="PigeonOS_0.12_Development/Pigeon"

INSTALL_DIR="${1:-}"
if [[ -z "${INSTALL_DIR}" ]]; then
  for d in "${HOME}"/Pigeon_*; do
    if [[ -f "${d}/installer/run_pigeon_0_12.sh" && ( -f "${d}/pigeonSystem/pigeon_0_12.py" || -f "${d}/pigeonSystem/pigeon_0_9.py" ) ]]; then
      INSTALL_DIR="${d}"
      break
    fi
    if [[ -f "${d}/installer/run_pigeon_0_10.sh" && ( -f "${d}/pigeonSystem/pigeon_0_12.py" || -f "${d}/pigeonSystem/pigeon_0_9.py" ) ]]; then
      INSTALL_DIR="${d}"
      break
    fi
    # Legacy install trees (pre-0.9 entrypoint names).
    if [[ -f "${d}/installer/run_pigeon_0_8.sh" && -f "${d}/pigeonSystem/pigeon_0_8.py" ]]; then
      INSTALL_DIR="${d}"
      break
    fi
  done
fi

if [[ -z "${INSTALL_DIR}" || ! -d "${INSTALL_DIR}" ]]; then
  echo "pigeon: could not find Pigeon install folder." >&2
  echo "Usage: $0 /path/to/Pigeon_X.Y.Z" >&2
  exit 1
fi

INSTALL_DIR="$(cd "${INSTALL_DIR}" && pwd)"
echo "==> Updating Pigeon at ${INSTALL_DIR}"
echo "==> Downloading ${ZIP_URL}"

# Remove bad GitHub tokens (narrow no-break space U+202F breaks old updaters).
rm -f "${HOME}/.pigeon_0_6/github_update_token"
unset PIGEON_UPDATE_GITHUB_TOKEN GITHUB_TOKEN GH_TOKEN GITHUB_PAT 2>/dev/null || true

for cmd in curl rsync python3; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "pigeon: ${cmd} is required. Run: sudo apt install curl rsync python3" >&2
    exit 1
  fi
done

WORKDIR="$(mktemp -d /tmp/pigeon-update.XXXXXX)"
trap 'rm -rf "${WORKDIR}"' EXIT

curl -fsSL -o "${WORKDIR}/pigeon.zip" "${ZIP_URL}"
python3 -X utf8 - <<'PY' "${WORKDIR}/pigeon.zip" "${WORKDIR}/extract" "${APP_REL}" || { echo "pigeon-update ERROR: archive extraction failed or was rejected as unsafe" >&2; exit 1; }
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
        sys.exit(f"update archive has too many entries ({len(infos)})")
    declared_total = 0
    for info in infos:
        if safe_target(info.filename) is None:
            sys.exit(f"unsafe path in update archive: {info.filename!r}")
        if marker in info.filename and not info.is_dir():
            if info.file_size > MAX_FILE_BYTES:
                sys.exit(f"update archive member too large: {info.filename!r}")
            declared_total += info.file_size
    if declared_total > MAX_TOTAL_BYTES:
        sys.exit(f"update archive expands to more than {MAX_TOTAL_BYTES} bytes")
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
                    sys.exit(f"update archive exceeds size limits at {name!r}")
                dst.write(chunk)
        # zipfile does not restore Unix modes; keep +x so rsync -a does not
        # strip it from installed launchers (systemd execs them directly).
        mode = (info.external_attr >> 16) & 0o777  # no setuid/setgid/sticky
        if mode:
            target.chmod(mode)
PY

EXTRACT="${WORKDIR}/extract"
SRC=""
for candidate in \
  "${EXTRACT}"/*/"${APP_REL}" \
  "${EXTRACT}/${APP_REL}" \
  "${EXTRACT}"/*; do
  if [[ -f "${candidate}/pigeonSystem/pigeon_0_12.py" || -f "${candidate}/pigeonSystem/pigeon_0_9.py" || -f "${candidate}/pigeonSystem/pigeon_0_8.py" ]]; then
    SRC="${candidate}"
    break
  fi
done

if [[ -z "${SRC}" || ! -d "${SRC}/pigeonSystem" ]]; then
  echo "pigeon: could not find ${APP_REL} inside GitHub zip." >&2
  exit 1
fi

echo "==> Merging app code and UI assets into ${INSTALL_DIR} (settings in ~/.pigeon_0_6 are not touched)…"
rsync -a \
  --exclude 'pigeonSystem/.venv' \
  --exclude 'pigeonCashe' \
  --exclude 'pigeonTMDB' \
  --exclude 'raspberryPi/dist' \
  --exclude 'pigeonSystem/__pycache__' \
  --exclude '.DS_Store' \
  "${SRC}/" "${INSTALL_DIR}/"

if [[ -d "${SRC}/pigeonAssets" ]]; then
  echo "==> Refreshing pigeonAssets (status bar, logos, poster chrome)…"
  rsync -a "${SRC}/pigeonAssets/" "${INSTALL_DIR}/pigeonAssets/"
fi

# Belt and braces: systemd execs run_pigeon_0_12.sh directly, so a stripped +x
# leaves the service in a 203/EXEC restart loop.
if [[ -d "${INSTALL_DIR}/installer" ]]; then
  chmod +x "${INSTALL_DIR}/installer/"*.sh 2>/dev/null || true
  chmod +x "${INSTALL_DIR}/installer/"*.command 2>/dev/null || true
  chmod +x "${INSTALL_DIR}/installer/Run-Pigeon" "${INSTALL_DIR}/installer/Install-Pigeon" 2>/dev/null || true
fi

# shellcheck source=common.sh
source "${INSTALL_DIR}/installer/common.sh"
pigeon_install_bundled_fonts "${INSTALL_DIR}" "${HOME}"

echo "==> Refreshing Python dependencies…"
bash "${INSTALL_DIR}/installer/run_pigeon_0_12.sh" --bootstrap-only

VER="$(python3 -c "import importlib.util; p='${INSTALL_DIR}/pigeonSystem/pigeon/version.py'; s=importlib.util.spec_from_file_location('pv', p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.version_string())")"
echo ""
echo "Pigeon ${VER} installed. Quit and relaunch Pigeon to run the new version."
