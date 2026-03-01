#!/usr/bin/env bash
set -euo pipefail

WORKFLOW_FILE="${WORKFLOW_FILE:-.github/workflows/build-windows.yml}"
REF="${REF:-$(git rev-parse --abbrev-ref HEAD)}"
DOWNLOAD_DIR="${DOWNLOAD_DIR:-artifacts/windows-runner}"
COPY_TO_DIST="${COPY_TO_DIST:-1}"

usage() {
  cat <<EOF
Usage:
  scripts/run_github_windows_build.sh [options]

Options:
  --ref <git-ref>            Branch/tag ref to run on (default: current branch)
  --workflow <file-or-name>  Workflow path/id/name
                             (default: .github/workflows/build-windows.yml)
  --download-dir <dir>       Local directory for downloaded artifacts
                             (default: artifacts/windows-runner)
  --no-copy-dist             Do not copy SerialUI-*.zip into local dist/
  -h, --help                 Show help

Environment overrides:
  REF=<git-ref>
  WORKFLOW_FILE=<file-or-name>
  DOWNLOAD_DIR=<dir>
  COPY_TO_DIST=0|1

Notes:
  - Requires GitHub CLI (gh) authenticated for this repo.
  - The ref must already be pushed to GitHub.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref)
      REF="$2"
      shift 2
      ;;
    --workflow)
      WORKFLOW_FILE="$2"
      shift 2
      ;;
    --download-dir)
      DOWNLOAD_DIR="$2"
      shift 2
      ;;
    --no-copy-dist)
      COPY_TO_DIST=0
      shift
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

require_cmd() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "Error: required command not found: $name" >&2
    exit 2
  fi
}

require_cmd gh
require_cmd git

if ! gh auth status >/dev/null 2>&1; then
  echo "Error: gh is not authenticated. Run: gh auth login" >&2
  exit 2
fi

if [[ -z "${REF}" ]]; then
  echo "Error: unable to determine git ref. Provide --ref." >&2
  exit 2
fi

START_ISO="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"

echo "Triggering workflow '${WORKFLOW_FILE}' on ref '${REF}'..."
if ! gh workflow run "${WORKFLOW_FILE}" --ref "${REF}"; then
  # Some repos keep stale/deleted workflow names around; retry with canonical path.
  if [[ "${WORKFLOW_FILE}" != ".github/workflows/build-windows.yml" ]]; then
    echo "Retrying dispatch with canonical workflow path '.github/workflows/build-windows.yml'..."
    gh workflow run ".github/workflows/build-windows.yml" --ref "${REF}"
    WORKFLOW_FILE=".github/workflows/build-windows.yml"
  else
    exit 1
  fi
fi

RUN_ID=""
for _ in {1..30}; do
  RUN_ID="$(
    gh run list \
      --workflow "${WORKFLOW_FILE}" \
      --limit 20 \
      --json databaseId,createdAt \
      --jq "[.[] | select(.createdAt >= \"${START_ISO}\")][0].databaseId // empty"
  )"
  if [[ -n "${RUN_ID}" ]]; then
    break
  fi
  sleep 3
done

if [[ -z "${RUN_ID}" ]]; then
  echo "Error: could not find newly triggered run. Check Actions tab manually." >&2
  exit 2
fi

echo "Watching run: ${RUN_ID}"
gh run watch "${RUN_ID}" --exit-status

echo "Downloading artifacts to '${DOWNLOAD_DIR}'..."
rm -rf "${DOWNLOAD_DIR}"
mkdir -p "${DOWNLOAD_DIR}"
gh run download "${RUN_ID}" --dir "${DOWNLOAD_DIR}"

echo "Downloaded artifact contents:"
find "${DOWNLOAD_DIR}" -maxdepth 3 -type f | sed 's#^#  - #'

mapfile -t BUILT_ZIPS < <(find "${DOWNLOAD_DIR}" -type f -name 'SerialUI-[0-9]*.zip' | sort)
if [[ "${#BUILT_ZIPS[@]}" -eq 0 ]]; then
  if command -v unzip >/dev/null 2>&1; then
    echo "No packaged executable zips found directly; extracting downloaded artifact zip containers..."
    EXTRACT_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/serialui-artifacts.XXXXXX")"
    while IFS= read -r artifact_zip; do
      unzip -q -o "${artifact_zip}" -d "${EXTRACT_ROOT}/$(basename "${artifact_zip}" .zip)" || true
    done < <(find "${DOWNLOAD_DIR}" -type f -name '*.zip' | sort)
    mapfile -t BUILT_ZIPS < <(find "${EXTRACT_ROOT}" -type f -name 'SerialUI-[0-9]*.zip' | sort)
  fi
fi
if [[ "${#BUILT_ZIPS[@]}" -eq 0 ]]; then
  echo "Warning: no packaged SerialUI-<version>-*.zip found in downloaded artifacts." >&2
  exit 1
fi

if [[ "${COPY_TO_DIST}" == "1" ]]; then
  mkdir -p dist
  for zip_path in "${BUILT_ZIPS[@]}"; do
    cp -f "${zip_path}" dist/
    echo "Copied to dist/: $(basename "${zip_path}")"
  done
fi

echo "Done."
