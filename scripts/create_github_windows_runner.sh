#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SETUP_SH="${REPO_ROOT}/scripts/setup.sh"
WORKFLOW_FILE="${REPO_ROOT}/.github/workflows/build-windows.yml"
WINDOWS_AMD64_PYTHON="${WINDOWS_AMD64_PYTHON:-3.10}"
WINDOWS_ARM64_PYTHON="${WINDOWS_ARM64_PYTHON:-3.11}"
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
  --python-version <ver>         Python version for both amd64 and arm64 runners
                                 (default: amd64=${WINDOWS_AMD64_PYTHON}, arm64=${WINDOWS_ARM64_PYTHON})
  --windows-amd64-python <ver>   Python version for amd64 runner
                                 (default: ${WINDOWS_AMD64_PYTHON})
  --windows-arm64-python <ver>   Python version for arm64 runner
                                 (default: ${WINDOWS_ARM64_PYTHON})
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
    --python-version) WINDOWS_AMD64_PYTHON="$2"; WINDOWS_ARM64_PYTHON="$2"; shift 2 ;;
    --windows-amd64-python) WINDOWS_AMD64_PYTHON="$2"; shift 2 ;;
    --windows-arm64-python) WINDOWS_ARM64_PYTHON="$2"; shift 2 ;;
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
            python_version: '${WINDOWS_AMD64_PYTHON}'
            pip_packages: "${PIP_INSTALL_LINE}"
EOF
)
if [[ "${INCLUDE_ARM64}" == "1" ]]; then
  MATRIX_INCLUDE+=$'\n'"          - runner: ${WINDOWS_ARM64_RUNNER}"$'\n'"            arch: arm64"$'\n'"            python_version: '${WINDOWS_ARM64_PYTHON}'"$'\n'"            pip_packages: \"${PIP_INSTALL_LINE_ARM64}\""
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
        id: setup_python
        uses: actions/setup-python@v5
        with:
          python-version: \${{ matrix.python_version }}

      - name: Show Python version
        shell: pwsh
        run: |
          python --version
          python -c "import sys; print(sys.version)"

      - name: Install app dependencies
        shell: pwsh
        run: |
          python -m pip install --upgrade pip
          python -m pip install \${{ matrix.pip_packages }}

      - name: Build executable archive via release.ps1 (with C-accelerated line parser)
        id: build_executable
        shell: pwsh
        run: |
          .\scripts\release.ps1 -PythonBin python -BuildExecutable -BuildCAccelerated

      - name: Remove bundled MSVCP140.dll files (defensive)
        shell: pwsh
        run: |
          \$internalDir = ".\dist\SerialUI\_internal"
          \$dlls = Get-ChildItem -Path \$internalDir -Recurse -Filter MSVCP140.dll -ErrorAction SilentlyContinue
          if (\$dlls) {
            \$dlls | ForEach-Object {
              Remove-Item -Force \$_.FullName
              Write-Host "Removed bundled runtime file:"
              Write-Host \$_.FullName
            }
          } else {
            Write-Host "No bundled MSVCP140.dll files found under \$internalDir"
          }

      - name: Frozen self-test (C parser)
        id: c_parser_selftest
        shell: pwsh
        run: |
          & .\dist\SerialUI\SerialUI.exe --selftest-c-parser
          \$exitCode = \$LASTEXITCODE
          Write-Host "C parser self-test exit code: \$exitCode"
          if (\$exitCode -ne 0) { throw "Frozen C parser self-test failed with exit code \$exitCode" }

      - name: Frozen self-test (numba)
        id: numba_selftest
        if: \${{ matrix.arch != 'arm64' && steps.c_parser_selftest.conclusion == 'success' }}
        shell: pwsh
        run: |
          & .\dist\SerialUI\SerialUI.exe --selftest-numba
          \$exitCode = \$LASTEXITCODE
          Write-Host "Numba self-test exit code: \$exitCode"
          if (\$exitCode -ne 0) { throw "Frozen numba self-test failed with exit code \$exitCode" }

      - name: Crash diagnostics (Windows event logs)
        if: \${{ always() && (steps.setup_python.conclusion == 'failure' || steps.build_executable.conclusion == 'failure' || steps.c_parser_selftest.conclusion == 'failure' || (matrix.arch != 'arm64' && steps.numba_selftest.conclusion == 'failure')) }}
        shell: pwsh
        run: |
          Write-Host "Step outcomes:"
          Write-Host "  setup_python:      \${{ steps.setup_python.conclusion }}"
          Write-Host "  build_executable:  \${{ steps.build_executable.conclusion }}"
          Write-Host "  c_parser_selftest: \${{ steps.c_parser_selftest.conclusion }}"
          Write-Host "  numba_selftest:    \${{ steps.numba_selftest.conclusion }}"

          Write-Host "Collecting recent Application Error events for SerialUI.exe"
          \$events = Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1000; StartTime=(Get-Date).AddMinutes(-30)} -ErrorAction SilentlyContinue |
            Where-Object { \$_.Message -match 'Faulting application name: SerialUI.exe' } |
            Select-Object -First 5 -ExpandProperty Message
          if (\$events) {
            \$events | ForEach-Object { Write-Host "-----"; Write-Host \$_ }
          } else {
            Write-Host "No matching Application Error (ID=1000) events found in the last 30 minutes."
          }

          Write-Host "Recent Application log events related to SerialUI/parser/runtime:"
          Get-WinEvent -FilterHashtable @{LogName='Application'; StartTime=(Get-Date).AddMinutes(-30)} -ErrorAction SilentlyContinue |
            Where-Object { \$_.Message -match 'SerialUI.exe|simple_parser|header_parser|python3[0-9]{2}\.dll|MSVCP140.dll' } |
            Select-Object -First 10 TimeCreated, Id, ProviderName, Message |
            Format-List

          Write-Host "Checking for remaining bundled MSVCP140.dll files"
          Get-ChildItem .\dist\SerialUI\_internal -Recurse -Filter MSVCP140.dll -ErrorAction SilentlyContinue |
            Select-Object FullName, Length

          Write-Host "Checking bundled parser extensions"
          Get-ChildItem .\dist\SerialUI\_internal -Recurse -Filter *.pyd -ErrorAction SilentlyContinue |
            Where-Object { \$_.Name -match 'simple_parser|header_parser' } |
            Select-Object FullName, Length

      - name: Upload build artifacts
        if: \${{ always() && steps.build_executable.conclusion == 'success' }}
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
