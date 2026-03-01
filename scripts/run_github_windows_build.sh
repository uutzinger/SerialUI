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

REPO_SLUG="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
if [[ -z "${REPO_SLUG}" ]]; then
  echo "Error: unable to resolve repository slug via gh repo view." >&2
  exit 2
fi

WORKFLOW_TABLE="$(
  gh api "repos/${REPO_SLUG}/actions/workflows" --paginate \
    --jq '.workflows[] | [.id,.path,.name,.state] | @tsv'
)"

WORKFLOW_ID=""
WORKFLOW_PATH=""
WORKFLOW_NAME=""
if [[ "${WORKFLOW_FILE}" =~ ^[0-9]+$ ]]; then
  WORKFLOW_ID="${WORKFLOW_FILE}"
  RESOLVED_LINE="$(printf '%s\n' "${WORKFLOW_TABLE}" | awk -F '\t' -v wid="${WORKFLOW_ID}" '$1==wid {print; exit}')"
else
  RESOLVED_LINE="$(printf '%s\n' "${WORKFLOW_TABLE}" | awk -F '\t' -v wf="${WORKFLOW_FILE}" '$2==wf {print; exit}')"
  if [[ -z "${RESOLVED_LINE}" ]]; then
    WF_CANON=".github/workflows/${WORKFLOW_FILE##*/}"
    RESOLVED_LINE="$(printf '%s\n' "${WORKFLOW_TABLE}" | awk -F '\t' -v wf="${WF_CANON}" '$2==wf {print; exit}')"
  fi
  if [[ -z "${RESOLVED_LINE}" ]]; then
    RESOLVED_LINE="$(printf '%s\n' "${WORKFLOW_TABLE}" | awk -F '\t' -v wf="${WORKFLOW_FILE##*/}" '$2 ~ ("/" wf "$") || $3==wf {print; exit}')"
  fi
  if [[ -n "${RESOLVED_LINE}" ]]; then
    WORKFLOW_ID="$(printf '%s' "${RESOLVED_LINE}" | awk -F '\t' '{print $1}')"
  fi
fi

if [[ -z "${WORKFLOW_ID}" ]]; then
  echo "Error: could not resolve workflow '${WORKFLOW_FILE}' in repo ${REPO_SLUG}." >&2
  echo "Known workflows:" >&2
  printf '%s\n' "${WORKFLOW_TABLE}" | awk -F '\t' '{printf("  - id=%s path=%s name=%s state=%s\n",$1,$2,$3,$4)}' >&2
  exit 2
fi

if [[ -z "${RESOLVED_LINE:-}" ]]; then
  RESOLVED_LINE="$(printf '%s\n' "${WORKFLOW_TABLE}" | awk -F '\t' -v wid="${WORKFLOW_ID}" '$1==wid {print; exit}')"
fi
WORKFLOW_PATH="$(printf '%s' "${RESOLVED_LINE}" | awk -F '\t' '{print $2}')"
WORKFLOW_NAME="$(printf '%s' "${RESOLVED_LINE}" | awk -F '\t' '{print $3}')"
WORKFLOW_STATE="$(printf '%s' "${RESOLVED_LINE}" | awk -F '\t' '{print $4}')"

echo "Resolved workflow: id=${WORKFLOW_ID} path=${WORKFLOW_PATH} name=${WORKFLOW_NAME} state=${WORKFLOW_STATE}"

START_ISO="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"

echo "Triggering workflow id '${WORKFLOW_ID}' on ref '${REF}'..."
if ! gh api -X POST "repos/${REPO_SLUG}/actions/workflows/${WORKFLOW_ID}/dispatches" -f "ref=${REF}"; then
  echo "Dispatch failed. Showing first lines of ${WORKFLOW_PATH} at ref '${REF}' for trigger debugging:" >&2
  gh api -H "Accept: application/vnd.github.raw+json" "repos/${REPO_SLUG}/contents/${WORKFLOW_PATH}?ref=${REF}" | sed -n '1,40p' >&2 || true
  exit 1
fi

RUN_ID=""
for _ in {1..30}; do
  RUN_ID="$(
    gh run list \
      --workflow "${WORKFLOW_ID}" \
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
