#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SETUP_SH="${REPO_ROOT}/scripts/setup.sh"
WORKFLOW_FILE="${REPO_ROOT}/.github/workflows/build-raspbian.yml"
PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
RASPBIAN_LABELS="${RASPBIAN_LABELS:-self-hosted,linux,arm64,raspbian}"

usage() {
  cat <<EOF
Usage:
  scripts/create_github_raspbian_runner.sh [options]

Options:
  --workflow-file <path>    Workflow output path
                            (default: .github/workflows/build-raspbian.yml)
  --python-version <ver>    Python version for setup-python
                            (default: ${PYTHON_VERSION})
  --labels <csv>            runs-on labels, comma-separated
                            (default: ${RASPBIAN_LABELS})
  -h, --help                Show this help

Notes:
  - This workflow targets self-hosted Raspberry Pi runners.
  - Configure your runner with all labels provided in --labels.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workflow-file) WORKFLOW_FILE="$2"; shift 2 ;;
    --python-version) PYTHON_VERSION="$2"; shift 2 ;;
    --labels) RASPBIAN_LABELS="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
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
PIP_INSTALL_LINE="${PIP_INSTALL_LINE% } pyudev"

RUNS_ON_ITEMS=()
IFS=',' read -r -a LABEL_ARRAY <<< "${RASPBIAN_LABELS}"
for raw_label in "${LABEL_ARRAY[@]}"; do
  label="$(echo "${raw_label}" | xargs)"
  if [[ -n "${label}" ]]; then
    RUNS_ON_ITEMS+=("      - ${label}")
  fi
done

if [[ "${#RUNS_ON_ITEMS[@]}" -eq 0 ]]; then
  echo "Error: no valid labels parsed from --labels." >&2
  exit 2
fi

mkdir -p "$(dirname "${WORKFLOW_FILE}")"

{
  cat <<EOF
name: Build Raspbian Executable

on:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  build-raspbian:
    runs-on:
EOF
  printf '%s\n' "${RUNS_ON_ITEMS[@]}"
  cat <<EOF
    steps:
      - name: Checkout source
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '${PYTHON_VERSION}'

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

      - name: Frozen self-tests (C parser + numba)
        shell: bash
        run: |
          FROZEN_EXE=""
          if [[ -x "dist/SerialUI/SerialUI" ]]; then
            FROZEN_EXE="dist/SerialUI/SerialUI"
          elif [[ -x "dist/SerialUI.app/Contents/MacOS/SerialUI" ]]; then
            FROZEN_EXE="dist/SerialUI.app/Contents/MacOS/SerialUI"
          else
            echo "Frozen executable not found for self-tests." >&2
            exit 1
          fi
          "\${FROZEN_EXE}" --selftest-c-parser
          "\${FROZEN_EXE}" --selftest-numba

      - name: Upload build artifacts
        uses: actions/upload-artifact@v4
        with:
          name: SerialUI-raspbian-\${{ github.ref_name }}-\${{ github.run_number }}
          if-no-files-found: error
          retention-days: 14
          path: |
            dist/SerialUI-*.zip
            dist/SerialUI
EOF
} > "${WORKFLOW_FILE}"

echo "Created workflow: ${WORKFLOW_FILE}"
echo "runs-on labels:"
printf '  - %s\n' "${LABEL_ARRAY[@]}"
echo "Packages from setup.sh COMMON_PACKAGES + raspbian extras:"
printf '  - %s\n' "${COMMON_PACKAGES[@]}"
echo "  - pyudev"
