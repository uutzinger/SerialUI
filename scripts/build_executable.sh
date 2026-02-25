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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
HELPERS_DIR="${ROOT_DIR}/helpers"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BUILD_C_ACCEL="${BUILD_C_ACCEL:-1}"

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
run env PYTHONNOUSERSITE=1 "${PYTHON_BIN}" -m PyInstaller --clean --noconfirm SerialUI.spec
run ls -lh dist
popd >/dev/null

log "Done"
echo "Wheel artifacts: ${HELPERS_DIR}/dist"
echo "Standalone app:  ${ROOT_DIR}/dist/SerialUI"
