#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

RUN_LINUX=1
RUN_MACOS=1
RUN_WINDOWS=1
RUN_RASPBIAN=0
COMMIT_MSG=""
BUILD_REF=""
COMMIT_ONLY=0

usage() {
  cat <<'EOF'
Usage:
  scripts/build_release_all.sh [options]

Pipeline:
  1) Run release.sh with commit/tag/push for a new tag, then create-release
     If the version tag already exists locally, skip commit/tag/push and reuse it.
  2) Start Publish Release Assets on the repository's default branch
  3) Wait for builds and asset publication entirely within GitHub
     Existing tag-triggered builds and published packages are reused.
     No packages are downloaded to this computer or uploaded from it.

Options:
  --commit-msg "msg" Set custom commit message passed to release.sh
  --commit-only      Stage and commit, then stop before tag, push, release, or build
  --build-ref <ref>  Git branch/tag ref used for GitHub runner builds
                     (default: release version tag from config.py)
                     Must point to the same commit as the release tag.
  --skip-linux       Omit Linux packages
  --skip-macos       Omit macOS packages
  --skip-windows     Omit Windows packages
  --with-raspbian    Include Raspbian packages (requires self-hosted runner)
  --skip-raspbian    Skip Raspbian runner build
  -h, --help         Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --commit-msg)
      [[ $# -ge 2 ]] || { echo "Error: --commit-msg requires a value" >&2; exit 2; }
      COMMIT_MSG="$2"
      shift 2
      ;;
    --commit-only) COMMIT_ONLY=1; shift ;;
    --build-ref)
      [[ $# -ge 2 ]] || { echo "Error: --build-ref requires a value" >&2; exit 2; }
      BUILD_REF="$2"
      shift 2
      ;;
    --skip-linux) RUN_LINUX=0; shift ;;
    --skip-macos) RUN_MACOS=0; shift ;;
    --skip-windows) RUN_WINDOWS=0; shift ;;
    --with-raspbian) RUN_RASPBIAN=1; shift ;;
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
require_cmd python3
require_file "scripts/release.sh"

VERSION="$(project_version)"
echo "Release version from config.py: ${VERSION}"

if [[ "${COMMIT_ONLY}" -eq 1 ]]; then
  RELEASE_ARGS=(--commit)
  if [[ -n "${COMMIT_MSG}" ]]; then
    RELEASE_ARGS=(--commit-msg "${COMMIT_MSG}" "${RELEASE_ARGS[@]}")
  fi
  echo "Commit-only: Running release.sh ${RELEASE_ARGS[*]}"
  bash scripts/release.sh "${RELEASE_ARGS[@]}"
  echo "Commit-only complete; skipped tag, push, release, and builds."
  exit 0
fi

require_cmd gh

# Match release.sh: use stored authentication instead of stale environment tokens.
gh() { env -u GITHUB_TOKEN -u GH_TOKEN gh "$@"; }

if ! gh auth status >/dev/null 2>&1; then
  echo "Error: gh is not authenticated. Run: gh auth login" >&2
  exit 2
fi

PLATFORMS=()
if [[ "${RUN_LINUX}" -eq 1 ]]; then PLATFORMS+=(linux); fi
if [[ "${RUN_MACOS}" -eq 1 ]]; then PLATFORMS+=(macos); fi
if [[ "${RUN_WINDOWS}" -eq 1 ]]; then PLATFORMS+=(windows); fi
if [[ "${RUN_RASPBIAN}" -eq 1 ]]; then PLATFORMS+=(raspbian); fi
if [[ "${#PLATFORMS[@]}" -eq 0 ]]; then
  echo "Error: select at least one platform." >&2
  exit 2
fi
PLATFORM_LIST="$(IFS=,; echo "${PLATFORMS[*]}")"
REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
WORKFLOW_REF="$(gh repo view --json defaultBranchRef --jq .defaultBranchRef.name)"
# Check before committing/tagging that remote publication is available.
gh api "repos/${REPO}/actions/workflows/publish-release-assets.yml" >/dev/null

if [[ -z "${BUILD_REF}" ]]; then
  BUILD_REF="${VERSION}"
fi
echo "GitHub runner build ref: ${BUILD_REF}"

EXISTING_TAG=0
if git rev-parse -q --verify "refs/tags/${VERSION}" >/dev/null 2>&1; then
  EXISTING_TAG=1
  echo "Tag ${VERSION} already exists locally; reusing it for runner builds and asset upload."
else
  HAS_CHANGES=0
  if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
    HAS_CHANGES=1
  fi

  RELEASE_ARGS=(--tag --push)
  if [[ "${HAS_CHANGES}" -eq 1 ]]; then
    RELEASE_ARGS=(--commit "${RELEASE_ARGS[@]}")
  else
    echo "No local changes detected; running release without --commit."
  fi

  if [[ -n "${COMMIT_MSG}" ]]; then
    RELEASE_ARGS=(--commit-msg "${COMMIT_MSG}" "${RELEASE_ARGS[@]}")
  fi
fi

echo ""
if [[ "${EXISTING_TAG}" -eq 0 ]]; then
  echo "Step 1/3: Running release.sh ${RELEASE_ARGS[*]}"
  bash scripts/release.sh "${RELEASE_ARGS[@]}"
else
  echo "Step 1/3: Skipping commit/tag/push for existing tag ${VERSION}"
fi
echo "Step 1/3: Running release.sh --create-release"
bash scripts/release.sh --create-release

echo ""
echo "Step 2/3: Publishing ${PLATFORM_LIST} packages within GitHub"
REQUEST_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
RUN_TITLE="Publish release ${VERSION} (${REQUEST_ID})"
gh workflow run publish-release-assets.yml --repo "${REPO}" --ref "${WORKFLOW_REF}" \
  -f "tag=${VERSION}" -f "build_ref=${BUILD_REF}" \
  -f "platforms=${PLATFORM_LIST}" -f "request_id=${REQUEST_ID}"

# Identify this exact dispatch rather than accidentally watching a concurrent run.
RUN_ID=""
for _ in {1..30}; do
  RUN_ID="$(gh run list --repo "${REPO}" --workflow publish-release-assets.yml \
    --event workflow_dispatch --limit 100 --json databaseId,displayTitle | \
    python3 -c 'import json, sys; print(next((str(r["databaseId"]) for r in json.load(sys.stdin) if r["displayTitle"] == sys.argv[1]), ""))' "${RUN_TITLE}")"
  if [[ -n "${RUN_ID}" ]]; then break; fi
  sleep 3
done
if [[ -z "${RUN_ID}" ]]; then
  echo "Error: could not find publication run '${RUN_TITLE}'. Check GitHub Actions before retrying." >&2
  exit 2
fi

echo ""
echo "Step 3/3: Waiting for publication run ${RUN_ID}"
gh run watch "${RUN_ID}" --repo "${REPO}" --exit-status
gh release view "${VERSION}" --repo "${REPO}" --json url --jq .url

echo ""
echo "Done."
