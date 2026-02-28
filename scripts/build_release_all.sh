#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

RUN_LINUX=1
RUN_MACOS=1
RUN_WINDOWS=1
RUN_RASPBIAN=0

usage() {
  cat <<'EOF'
Usage:
  scripts/build_release_all.sh [options]

Pipeline:
  1) Run release.sh with commit/tag/push/release
  2) Run runner builds (linux/macos/windows/raspbian) on the release tag
  3) Run release.sh --upload-assets

Options:
  --skip-linux       Skip Linux runner build
  --skip-macos       Skip macOS runner build
  --skip-windows     Skip Windows runner build
  --skip-raspbian    Skip Raspbian runner build
  -h, --help         Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-linux) RUN_LINUX=0; shift ;;
    --skip-macos) RUN_MACOS=0; shift ;;
    --skip-windows) RUN_WINDOWS=0; shift ;;
    --skip-raspbian) RUN_RASPBIAN=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

require_cmd() {
  local name="$1"
  if ! command -v "${name}" >/dev/null 2>&1; then
    echo "Error: required command not found: ${name}" >&2
    exit 2
  fi
}

require_file() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    echo "Error: required file missing: ${path}" >&2
    exit 2
  fi
}

project_version() {
  python3 - <<'PY'
import ast
from pathlib import Path

config_file = Path("config.py")
module = ast.parse(config_file.read_text(encoding="utf-8"), filename=str(config_file))
for node in module.body:
    value = None
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "VERSION":
                value = node.value
                break
    elif isinstance(node, ast.AnnAssign):
        if isinstance(node.target, ast.Name) and node.target.id == "VERSION":
            value = node.value
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        print(value.value)
        raise SystemExit(0)
raise SystemExit("VERSION was not found as a string literal in config.py")
PY
}

require_cmd git
require_cmd gh
require_cmd python3
require_file "scripts/release.sh"
require_file "scripts/run_github_linux_build.sh"
require_file "scripts/run_github_mac_build.sh"
require_file "scripts/run_github_windows_build.sh"
require_file "scripts/run_github_raspbian_build.sh"

if ! gh auth status >/dev/null 2>&1; then
  echo "Error: gh is not authenticated. Run: gh auth login" >&2
  exit 2
fi

VERSION="$(project_version)"
echo "Release version from config.py: ${VERSION}"

if git rev-parse -q --verify "refs/tags/${VERSION}" >/dev/null 2>&1; then
  echo "Error: git tag '${VERSION}' already exists locally. Bump VERSION before running this pipeline." >&2
  exit 2
fi

HAS_CHANGES=0
if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  HAS_CHANGES=1
fi

RELEASE_ARGS=(--tag --push --release)
if [[ "${HAS_CHANGES}" -eq 1 ]]; then
  RELEASE_ARGS=(--commit "${RELEASE_ARGS[@]}")
else
  echo "No local changes detected; running release without --commit."
fi

echo ""
echo "Step 1/3: Running release.sh ${RELEASE_ARGS[*]}"
bash scripts/release.sh "${RELEASE_ARGS[@]}"

echo ""
echo "Step 2/3: Running runner builds on tag ${VERSION}"
if [[ "${RUN_LINUX}" -eq 1 ]]; then
  bash scripts/run_github_linux_build.sh --ref "${VERSION}"
fi
if [[ "${RUN_MACOS}" -eq 1 ]]; then
  bash scripts/run_github_mac_build.sh --ref "${VERSION}"
fi
if [[ "${RUN_WINDOWS}" -eq 1 ]]; then
  bash scripts/run_github_windows_build.sh --ref "${VERSION}"
fi
if [[ "${RUN_RASPBIAN}" -eq 1 ]]; then
  bash scripts/run_github_raspbian_build.sh --ref "${VERSION}"
fi

echo ""
echo "Step 3/3: Uploading downloaded artifacts from local dist/ to GitHub release ${VERSION}"
bash scripts/release.sh --upload-assets

echo ""
echo "Done."
