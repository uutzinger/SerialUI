#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SETUP_SH="${REPO_ROOT}/scripts/setup.sh"
WORKFLOW_FILE="${REPO_ROOT}/.github/workflows/build-windows.yml"
PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
WINDOWS_AMD64_RUNNER="${WINDOWS_AMD64_RUNNER:-windows-2022}"
WINDOWS_ARM64_RUNNER="${WINDOWS_ARM64_RUNNER:-windows-11-arm}"
INCLUDE_ARM64="${INCLUDE_ARM64:-1}"

usage() {
  cat <<EOF
Usage:
  scripts/create_github_windows_runner.sh [options]

Options:
  --workflow-file <path>         Workflow output path
                                 (default: .github/workflows/build-windows.yml)
  --python-version <ver>         Python version for setup-python
                                 (default: ${PYTHON_VERSION})
  --windows-amd64-runner <name>  Runner label for amd64 build
                                 (default: ${WINDOWS_AMD64_RUNNER})
  --windows-arm64-runner <name>  Runner label for arm64 build
                                 (default: ${WINDOWS_ARM64_RUNNER})
  --no-arm64                     Disable arm64 matrix entry
  -h, --help                     Show this help

Notes:
  - Windows arm64 hosted runner availability depends on your GitHub plan.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workflow-file) WORKFLOW_FILE="$2"; shift 2 ;;
    --python-version) PYTHON_VERSION="$2"; shift 2 ;;
    --windows-amd64-runner) WINDOWS_AMD64_RUNNER="$2"; shift 2 ;;
    --windows-arm64-runner) WINDOWS_ARM64_RUNNER="$2"; shift 2 ;;
    --no-arm64) INCLUDE_ARM64=0; shift ;;
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
PIP_INSTALL_LINE="${PIP_INSTALL_LINE% } wmi"
PIP_INSTALL_LINE_ARM64="$(printf '%s\n' "${COMMON_PACKAGES[@]}" | awk '$0 != "numba" {printf("%s ", $0)}')"
PIP_INSTALL_LINE_ARM64="${PIP_INSTALL_LINE_ARM64% } wmi"

MATRIX_INCLUDE=$(cat <<EOF
          - runner: ${WINDOWS_AMD64_RUNNER}
            arch: amd64
            pip_packages: "${PIP_INSTALL_LINE}"
EOF
)
if [[ "${INCLUDE_ARM64}" == "1" ]]; then
  MATRIX_INCLUDE+=$'\n'"          - runner: ${WINDOWS_ARM64_RUNNER}"$'\n'"            arch: arm64"$'\n'"            pip_packages: \"${PIP_INSTALL_LINE_ARM64}\""
fi

mkdir -p "$(dirname "${WORKFLOW_FILE}")"

cat > "${WORKFLOW_FILE}" <<EOF
name: Build Windows Executable

on:
  workflow_dispatch:
  push:
    tags:
      - '*'

permissions:
  contents: read

jobs:
  build-windows:
    strategy:
      fail-fast: false
      matrix:
        include:
${MATRIX_INCLUDE}
    runs-on: \${{ matrix.runner }}
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
        shell: pwsh
        run: |
          python -m pip install --upgrade pip
          python -m pip install \${{ matrix.pip_packages }}

      - name: Build executable archive via release.ps1 (with C-accelerated line parser)
        shell: pwsh
        run: |
          .\scripts\release.ps1 -PythonBin python -BuildExecutable -BuildCAccelerated

      - name: Upload build artifacts
        uses: actions/upload-artifact@v4
        with:
          name: SerialUI-windows-\${{ matrix.arch }}-\${{ github.ref_name }}-\${{ github.run_number }}
          if-no-files-found: error
          retention-days: 14
          path: |
            dist/SerialUI-*.zip
            dist/SerialUI
EOF

echo "Created workflow: ${WORKFLOW_FILE}"
echo "Packages from setup.sh COMMON_PACKAGES + windows extras:"
printf '  - %s\n' "${COMMON_PACKAGES[@]}"
echo "  - wmi"
echo "Windows arm64 package override excludes: numba"
if [[ "${INCLUDE_ARM64}" == "1" ]]; then
  echo "Windows arm64 matrix enabled (runner: ${WINDOWS_ARM64_RUNNER})."
fi
