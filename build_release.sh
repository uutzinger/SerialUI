#!/usr/bin/env bash
set -euo pipefail

# End-to-end release/build script for SerialUI + line_parsers.
#
# What it does:
# 1) Installs/upgrades build tooling
# 2) Builds C extensions in helpers/line_parsers
# 3) Builds wheel/sdist for helpers package (line_parsers)
# 4) Runs twine check
# 5) Reinstalls the freshly built wheel locally
# 6) Optionally uploads to PyPI
# 7) Builds standalone app via PyInstaller spec
#
# Usage:
#   ./build_release.sh
#
# Optional environment variables:
#   PYTHON_BIN=python3
#   PACKAGE_NAME=line_parsers
#   UPLOAD_PYPI=1
#   TWINE_USERNAME=__token__
#   TWINE_PASSWORD=<your-token>
#   TWINE_REPOSITORY_URL=https://upload.pypi.org/legacy/

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPERS_DIR="${ROOT_DIR}/helpers"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PACKAGE_NAME="${PACKAGE_NAME:-line_parsers}"
UPLOAD_PYPI="${UPLOAD_PYPI:-0}"
TWINE_REPOSITORY_URL="${TWINE_REPOSITORY_URL:-https://upload.pypi.org/legacy/}"

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
import site, sys
prefix = sys.prefix.rstrip("/")
base = getattr(sys, "base_prefix", "").rstrip("/")
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
run "${PYTHON_BIN}" -m pip install --upgrade pip build twine pyinstaller pybind11 setuptools wheel

log "Building C-accelerated parsers"
pushd "${HELPERS_DIR}" >/dev/null
run "${PYTHON_BIN}" setup.py clean --all || true
run rm -rf build dist ./*.egg-info .eggs
run "${PYTHON_BIN}" setup.py build_ext --inplace -v

log "Building wheel and source distribution"
# Use the current environment (we installed build deps above),
# so builds don't fail in restricted/offline environments.
run "${PYTHON_BIN}" -m build --no-isolation
run "${PYTHON_BIN}" -m twine check dist/*
run ls -lh dist

WHEEL_FILE="$(ls -1t dist/*.whl | head -n 1)"
if [[ -z "${WHEEL_FILE}" ]]; then
    echo "No wheel file found in ${HELPERS_DIR}/dist" >&2
    exit 1
fi

log "Reinstalling built wheel locally (${WHEEL_FILE})"
run "${PYTHON_BIN}" -m pip uninstall -y "${PACKAGE_NAME}" || true
run "${PYTHON_BIN}" -m pip install --no-deps --force-reinstall --no-cache-dir "${WHEEL_FILE}"

if [[ "${UPLOAD_PYPI}" == "1" ]]; then
    log "Uploading distributions to PyPI"
    export TWINE_USERNAME="${TWINE_USERNAME:-__token__}"
    : "${TWINE_PASSWORD:?Set TWINE_PASSWORD when UPLOAD_PYPI=1}"
    run "${PYTHON_BIN}" -m twine upload --repository-url "${TWINE_REPOSITORY_URL}" dist/*
else
    log "Skipping PyPI upload (set UPLOAD_PYPI=1 to enable)"
fi
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
