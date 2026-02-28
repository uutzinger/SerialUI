#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/create_github_linux_runner.sh" \
  --workflow-file "${SCRIPT_DIR}/../.github/workflows/build-linux-arm64.yml" \
  --workflow-name "Build Linux Executable (ARM64)" \
  --no-amd64 \
  "$@"
