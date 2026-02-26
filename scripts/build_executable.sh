#!/usr/bin/env bash
set -euo pipefail

# Build script for SerialUI + optional C-accelerated line parsers.
#
# What it does:
# 1) Installs/upgrades build tooling
# 2) Optionally builds C extensions in helpers/line_parsers
# 3) Builds wheel/sdist for helpers package (line_parsers)
# 4) Builds standalone app via PyInstaller spec
#
# Usage:
#   ./build_executable.sh
#
# Optional environment variables:
#   PYTHON_BIN=python3
#   BUILD_C_ACCEL=1
#   BUILD_PYTHONPATH=/home/uutzinger/Build/fastplotlib
#   NO_ZIP=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
HELPERS_DIR="${ROOT_DIR}/helpers"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BUILD_C_ACCEL="${BUILD_C_ACCEL:-1}"
BUILD_PYTHONPATH="${BUILD_PYTHONPATH:-}"
NO_ZIP="${NO_ZIP:-0}"

log() {
    printf '\n[%s] %s\n' "$(date +'%H:%M:%S')" "$*"
}

require_dir() {
    local d="$1"
    if [[ ! -d "${d}" ]]; then
        echo "Required directory does not exist: ${d}" >&2
        exit 1
    fi
}

require_file() {
    local f="$1"
    if [[ ! -f "${f}" ]]; then
        echo "Required file does not exist: ${f}" >&2
        exit 1
    fi
}

run() {
    echo "+ $*"
    "$@"
}

require_dir "${HELPERS_DIR}"
require_file "${ROOT_DIR}/SerialUI.spec"
require_file "${HELPERS_DIR}/setup.py"

log "Checking Python environment isolation"
if "${PYTHON_BIN}" - <<'PY'
import sys
paths = [p for p in sys.path if "site-packages" in p or "dist-packages" in p]
uses_system = any(
    p.startswith("/usr/lib") or p.startswith("/usr/local/lib")
    for p in paths
)
raise SystemExit(0 if uses_system else 1)
PY
then
    echo "WARNING: Python environment includes system site-packages."
    echo "         This can make PyInstaller bundles very large by pulling unrelated packages."
    echo "         Recommended: build in a clean venv with include-system-site-packages = false."
fi

log "Installing/upgrading build tools"
run "${PYTHON_BIN}" -m pip install --upgrade pip build pyinstaller pybind11 setuptools wheel

log "Preparing helpers package"
pushd "${HELPERS_DIR}" >/dev/null
run rm -rf build dist ./*.egg-info .eggs
if [[ "${BUILD_C_ACCEL}" == "1" ]]; then
    log "Building C-accelerated parsers"
    run env PYTHONWARNINGS="${PYTHONWARNINGS:-ignore::FutureWarning}" "${PYTHON_BIN}" setup.py build_ext --inplace -v
else
    log "Skipping in-place C-accelerated parser build (BUILD_C_ACCEL=${BUILD_C_ACCEL})"
fi

log "Building wheel and source distribution"
run env PYTHONWARNINGS="${PYTHONWARNINGS:-ignore::FutureWarning}" "${PYTHON_BIN}" -m build --no-isolation
run ls -lh dist
popd >/dev/null

log "Building standalone executable with PyInstaller"
pushd "${ROOT_DIR}" >/dev/null
# Ignore user-site packages (e.g. obsolete pathlib backport in ~/.local).
if [[ -n "${BUILD_PYTHONPATH}" ]]; then
    log "Using custom PYTHONPATH for PyInstaller build"
    run env PYTHONNOUSERSITE=1 PYTHONPATH="${BUILD_PYTHONPATH}" "${PYTHON_BIN}" -m PyInstaller --clean --noconfirm SerialUI.spec
else
    run env PYTHONNOUSERSITE=1 PYTHONPATH= "${PYTHON_BIN}" -m PyInstaller --clean --noconfirm SerialUI.spec
fi
run ls -lh dist
popd >/dev/null

if [[ "${NO_ZIP}" != "1" ]]; then
    log "Creating executable zip archive"
    if [[ ! -d "${ROOT_DIR}/dist/SerialUI" ]]; then
        echo "Expected executable directory not found: ${ROOT_DIR}/dist/SerialUI" >&2
        exit 1
    fi
    rm -f "${ROOT_DIR}/dist/SerialUI.zip"
    ROOT_DIR="${ROOT_DIR}" "${PYTHON_BIN}" - <<'PY'
import os
import shutil
from pathlib import Path

root = Path(os.environ["ROOT_DIR"])
src = root / "dist" / "SerialUI"
dst_base = root / "dist" / "SerialUI"
archive = shutil.make_archive(str(dst_base), "zip", root_dir=str(src.parent), base_dir=src.name)
print(f"Executable zip: {archive}")
PY
fi

log "Done"
echo "Wheel artifacts: ${HELPERS_DIR}/dist"
echo "Standalone app:  ${ROOT_DIR}/dist/SerialUI"
