#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SETUP_SH="${REPO_ROOT}/scripts/setup.sh"
WORKFLOW_FILE="${REPO_ROOT}/.github/workflows/build-linux.yml"
PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
UBUNTU_AMD64_RUNNER="${UBUNTU_AMD64_RUNNER:-ubuntu-24.04}"
UBUNTU22_AMD64_RUNNER="${UBUNTU22_AMD64_RUNNER:-ubuntu-22.04}"
UBUNTU_ARM64_RUNNER="${UBUNTU_ARM64_RUNNER:-ubuntu-24.04-arm}"
INCLUDE_AMD64="${INCLUDE_AMD64:-1}"
INCLUDE_UBUNTU22_AMD64="${INCLUDE_UBUNTU22_AMD64:-1}"
INCLUDE_ARM64="${INCLUDE_ARM64:-1}"
WORKFLOW_NAME="${WORKFLOW_NAME:-Build Linux Executables (AMD64 + ARM64)}"

usage() {
  cat <<EOF
Usage:
  scripts/create_github_linux_runner.sh [options]

Options:
  --workflow-file <path>        Workflow output path
                                (default: .github/workflows/build-linux.yml)
  --python-version <ver>        Python version for setup-python
                                (default: ${PYTHON_VERSION})
  --workflow-name <name>        Workflow display name in GitHub Actions
                                (default: ${WORKFLOW_NAME})
  --ubuntu-amd64-runner <name>  Runner label for amd64 build
                                (default: ${UBUNTU_AMD64_RUNNER})
  --ubuntu22-amd64-runner <name> Runner label for ubuntu 22.04 amd64 build
                                 (default: ${UBUNTU22_AMD64_RUNNER})
  --ubuntu-arm64-runner <name>  Runner label for arm64 build
                                (default: ${UBUNTU_ARM64_RUNNER})
  --no-amd64                    Exclude amd64 matrix entry
  --no-ubuntu22-amd64           Exclude ubuntu 22.04 amd64 matrix entry
  --no-arm64                    Exclude arm64 matrix entry
  -h, --help                    Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workflow-file) WORKFLOW_FILE="$2"; shift 2 ;;
    --python-version) PYTHON_VERSION="$2"; shift 2 ;;
    --workflow-name) WORKFLOW_NAME="$2"; shift 2 ;;
    --ubuntu-amd64-runner) UBUNTU_AMD64_RUNNER="$2"; shift 2 ;;
    --ubuntu22-amd64-runner) UBUNTU22_AMD64_RUNNER="$2"; shift 2 ;;
    --ubuntu-arm64-runner) UBUNTU_ARM64_RUNNER="$2"; shift 2 ;;
    --no-amd64) INCLUDE_AMD64=0; shift ;;
    --no-ubuntu22-amd64) INCLUDE_UBUNTU22_AMD64=0; shift ;;
    --no-arm64) INCLUDE_ARM64=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ "${INCLUDE_AMD64}" != "1" && "${INCLUDE_UBUNTU22_AMD64}" != "1" && "${INCLUDE_ARM64}" != "1" ]]; then
  echo "Error: all Linux matrix entries were disabled. Enable at least one target." >&2
  exit 2
fi

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

MATRIX_INCLUDE=""
if [[ "${INCLUDE_AMD64}" == "1" ]]; then
  MATRIX_INCLUDE+=$(cat <<EOF
          - runner: ${UBUNTU_AMD64_RUNNER}
            arch: x86_64
            os_id: ubuntu24
            os_name: linux-ubuntu24
EOF
)
fi
if [[ "${INCLUDE_UBUNTU22_AMD64}" == "1" ]]; then
  if [[ -n "${MATRIX_INCLUDE}" ]]; then
    MATRIX_INCLUDE+=$'\n'
  fi
  MATRIX_INCLUDE+=$(cat <<EOF
          - runner: ${UBUNTU22_AMD64_RUNNER}
            arch: x86_64
            os_id: ubuntu22
            os_name: linux-ubuntu22
EOF
)
fi
if [[ "${INCLUDE_ARM64}" == "1" ]]; then
  if [[ -n "${MATRIX_INCLUDE}" ]]; then
    MATRIX_INCLUDE+=$'\n'
  fi
  MATRIX_INCLUDE+=$(cat <<EOF
          - runner: ${UBUNTU_ARM64_RUNNER}
            arch: arm64
            os_id: ubuntu24
            os_name: linux-ubuntu24
EOF
)
fi

mkdir -p "$(dirname "${WORKFLOW_FILE}")"

cat > "${WORKFLOW_FILE}" <<EOF
name: ${WORKFLOW_NAME}

on:
  workflow_dispatch:
  push:
    tags:
      - '*'

permissions:
  contents: read

jobs:
  build-linux:
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
        shell: bash
        run: |
          python -m pip install --upgrade pip
          python -m pip install ${PIP_INSTALL_LINE}

      - name: Build executable archive via release.sh (with C-accelerated line parser)
        shell: bash
        env:
          PYTHON_BIN: python
          BUILD_OS_NAME: \${{ matrix.os_name }}
        run: |
          bash scripts/release.sh --build-c-executable --build-c-accelerated

      - name: Upload build artifacts
        uses: actions/upload-artifact@v4
        with:
          name: SerialUI-linux-\${{ matrix.os_id }}-\${{ matrix.arch }}-\${{ github.ref_name }}-\${{ github.run_number }}
          if-no-files-found: error
          retention-days: 14
          path: |
            dist/SerialUI-*.zip
            dist/SerialUI
EOF

echo "Created workflow: ${WORKFLOW_FILE}"
echo "Packages from setup.sh COMMON_PACKAGES + linux extras:"
printf '  - %s\n' "${COMMON_PACKAGES[@]}"
echo "  - pyudev"
