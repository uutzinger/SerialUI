#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SETUP_SH="${REPO_ROOT}/scripts/setup.sh"
WORKFLOW_FILE="${REPO_ROOT}/.github/workflows/build-macos.yml"
PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
RUNNER_LABEL="${RUNNER_LABEL:-macos-14}"

usage() {
  cat <<EOF
Usage:
  scripts/create_github_mac_runner.sh [options]

Options:
  --workflow-file <path>   Workflow output path
                           (default: .github/workflows/build-macos.yml)
  --python-version <ver>   Python version for setup-python
                           (default: ${PYTHON_VERSION})
  --runner <label>         GitHub runner label
                           (default: ${RUNNER_LABEL})
  -h, --help               Show this help

Environment overrides:
  PYTHON_VERSION=<ver>
  RUNNER_LABEL=<label>
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workflow-file)
      WORKFLOW_FILE="$2"
      shift 2
      ;;
    --python-version)
      PYTHON_VERSION="$2"
      shift 2
      ;;
    --runner)
      RUNNER_LABEL="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ ! -f "${SETUP_SH}" ]]; then
  echo "Error: ${SETUP_SH} not found." >&2
  exit 2
fi

mapfile -t COMMON_PACKAGES < <(
  awk '
    /^[[:space:]]*COMMON_PACKAGES=\(/ {in_list=1; next}
    in_list && /^[[:space:]]*\)/ {in_list=0; exit}
    in_list {
      sub(/#.*/, "", $0)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0)
      gsub(/^["'"'"']|["'"'"']$/, "", $0)
      if (length($0) > 0) print $0
    }
  ' "${SETUP_SH}"
)

if [[ "${#COMMON_PACKAGES[@]}" -eq 0 ]]; then
  echo "Error: failed to parse COMMON_PACKAGES from ${SETUP_SH}." >&2
  exit 2
fi

PIP_INSTALL_LINE="$(printf '%s ' "${COMMON_PACKAGES[@]}")"
PIP_INSTALL_LINE="${PIP_INSTALL_LINE% }"

mkdir -p "$(dirname "${WORKFLOW_FILE}")"

cat > "${WORKFLOW_FILE}" <<EOF
name: Build macOS Executable

on:
  workflow_dispatch:
  push:
    tags:
      - '*'

permissions:
  contents: read

jobs:
  build-macos:
    runs-on: ${RUNNER_LABEL}
    steps:
      - name: Checkout source
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '${PYTHON_VERSION}'

      - name: Install system dependencies
        shell: bash
        run: |
          brew update
          brew install libomp

      - name: Install app dependencies
        shell: bash
        run: |
          python -m pip install --upgrade pip
          python -m pip install ${PIP_INSTALL_LINE}

      - name: Build executable archive via release.sh (with C-accelerated line parser)
        shell: bash
        env:
          PYTHON_BIN: python
        run: |
          bash scripts/release.sh --build-c-executable --build-c-accelerated

      - name: Upload build artifacts
        uses: actions/upload-artifact@v4
        with:
          name: SerialUI-macos-\${{ github.ref_name }}-\${{ github.run_number }}
          if-no-files-found: error
          retention-days: 14
          path: |
            dist/SerialUI-*.zip
            dist/SerialUI
            dist/SerialUI.app
EOF

echo "Created workflow: ${WORKFLOW_FILE}"
echo "Packages from setup.sh COMMON_PACKAGES:"
printf '  - %s\n' "${COMMON_PACKAGES[@]}"
