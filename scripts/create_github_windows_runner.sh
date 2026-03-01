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
name: Build Windows Executables (AMD64 + ARM64)

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

      - name: Remove bundled Qt MSVCP140.dll (defensive)
        shell: pwsh
        run: |
          \$qtMsvcp = ".\dist\SerialUI\_internal\PyQt6\Qt6\bin\MSVCP140.dll"
          if (Test-Path -Path \$qtMsvcp -PathType Leaf) {
            Remove-Item -Force \$qtMsvcp
            Write-Host "Removed bundled Qt runtime: \$qtMsvcp"
          } else {
            Write-Host "Qt MSVCP140.dll not present in bundle."
          }

      - name: Frozen self-test (C parser)
        id: c_parser_selftest
        continue-on-error: true
        shell: pwsh
        run: |
          & .\dist\SerialUI\SerialUI.exe --selftest-c-parser
          if (\$LASTEXITCODE -ne 0) { throw "Frozen C parser self-test failed with exit code \$LASTEXITCODE" }

      - name: Frozen self-test (numba)
        id: numba_selftest
        if: \${{ matrix.arch != 'arm64' && steps.c_parser_selftest.outcome == 'success' }}
        continue-on-error: true
        shell: pwsh
        run: |
          & .\dist\SerialUI\SerialUI.exe --selftest-numba
          if (\$LASTEXITCODE -ne 0) { throw "Frozen numba self-test failed with exit code \$LASTEXITCODE" }

      - name: Crash diagnostics (Windows event logs)
        if: \${{ always() && (steps.c_parser_selftest.outcome == 'failure' || (matrix.arch != 'arm64' && steps.numba_selftest.outcome == 'failure')) }}
        shell: pwsh
        run: |
          Write-Host "Collecting recent Application Error events for SerialUI.exe"
          \$events = Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1000; StartTime=(Get-Date).AddMinutes(-30)} -ErrorAction SilentlyContinue |
            Where-Object { \$_.Message -match 'Faulting application name: SerialUI.exe' } |
            Select-Object -First 5 -ExpandProperty Message
          if (\$events) {
            \$events | ForEach-Object { Write-Host "-----"; Write-Host \$_ }
          } else {
            Write-Host "No matching Application Error (ID=1000) events found in the last 30 minutes."
          }
          Write-Host "Checking for bundled Qt MSVCP140.dll"
          Get-ChildItem .\dist\SerialUI\_internal -Recurse -Filter MSVCP140.dll -ErrorAction SilentlyContinue |
            Select-Object FullName, Length

      - name: Upload build artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: SerialUI-windows-\${{ matrix.arch }}-\${{ github.ref_name }}-\${{ github.run_number }}
          if-no-files-found: error
          retention-days: 14
          path: |
            dist/SerialUI-*.zip
            dist/SerialUI

      - name: Enforce self-test results
        if: always()
        shell: pwsh
        run: |
          \$failed = \$false
          if ('\${{ steps.c_parser_selftest.outcome }}' -ne 'success') {
            Write-Host "C parser self-test outcome: \${{ steps.c_parser_selftest.outcome }}"
            \$failed = \$true
          }
          if ('\${{ matrix.arch }}' -ne 'arm64' -and '\${{ steps.numba_selftest.outcome }}' -ne 'success') {
            Write-Host "Numba self-test outcome: \${{ steps.numba_selftest.outcome }}"
            \$failed = \$true
          }
          if (\$failed) {
            throw "Frozen self-tests failed. See crash diagnostics above."
          }
EOF

echo "Created workflow: ${WORKFLOW_FILE}"
echo "Packages from setup.sh COMMON_PACKAGES + windows extras:"
printf '  - %s\n' "${COMMON_PACKAGES[@]}"
echo "  - wmi"
echo "Windows arm64 package override excludes: numba"
if [[ "${INCLUDE_ARM64}" == "1" ]]; then
  echo "Windows arm64 matrix enabled (runner: ${WINDOWS_ARM64_RUNNER})."
fi
