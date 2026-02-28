#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKFLOW_FILE="${WORKFLOW_FILE:-build-linux-amd64.yml}"
DOWNLOAD_DIR="${DOWNLOAD_DIR:-artifacts/linux-amd64-runner}"
exec env WORKFLOW_FILE="${WORKFLOW_FILE}" DOWNLOAD_DIR="${DOWNLOAD_DIR}" \
  "${SCRIPT_DIR}/run_github_linux_build.sh" "$@"
