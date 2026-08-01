#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

require_file() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    echo "Error: required file missing: ${path}" >&2
    exit 2
  fi
}

require_dir() {
  local path="$1"
  if [[ ! -d "${path}" ]]; then
    echo "Error: required directory missing: ${path}" >&2
    exit 2
  fi
}

require_cmd() {
  local name="$1"
  if ! command -v "${name}" >/dev/null 2>&1; then
    echo "Error: required command not found: ${name}" >&2
    exit 2
  fi
}

git_no_env_token() {
  env -u GITHUB_TOKEN -u GH_TOKEN git "$@"
}

gh_no_env_token() {
  env -u GITHUB_TOKEN -u GH_TOKEN gh "$@"
}

collect_release_assets() {
  local version="$1"
  local -n out_ref="$2"
  out_ref=()

  shopt -s nullglob
  out_ref=(
    "dist/SerialUI-${version}-"*.zip
    "dist/SerialUI-${version}-"*.tar.gz
  )
  shopt -u nullglob
}

validate_version_format() {
  local version="$1"
  if [[ ! "${version}" =~ ^[0-9]+(\.[0-9]+){2}([a-zA-Z0-9._-]*)?$ ]]; then
    echo "Error: config.py VERSION must provide X.Y.Z (PEP 440-compatible suffixes allowed)." >&2
    exit 2
  fi
}

project_version() {
  "${PYTHON_BIN}" - <<'PY'
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

create_github_release() {
  local version="$1"
  local with_assets="${2:-1}"
  local allow_existing="${3:-0}"
  local tag="${version}"
  local assets=()
  local notes
  local notes_args=()

  require_cmd gh

  if ! gh_no_env_token auth status >/dev/null 2>&1; then
    echo "Error: gh is not authenticated. Run: gh auth login" >&2
    exit 2
  fi

  if ! git_no_env_token rev-parse -q --verify "refs/tags/${tag}" >/dev/null 2>&1; then
    echo "Error: tag ${tag} does not exist locally." >&2
    exit 2
  fi

  if gh_no_env_token release view "${tag}" >/dev/null 2>&1; then
    if [[ "${allow_existing}" -eq 1 ]]; then
      echo "GitHub release ${tag} already exists; skipping creation."
      return 0
    fi
    echo "Error: GitHub release ${tag} already exists." >&2
    exit 2
  fi

  if [[ "${with_assets}" -eq 1 ]]; then
    require_dir "dist"
    collect_release_assets "${version}" assets
    if [[ "${#assets[@]}" -eq 0 ]]; then
      echo "Error: no release assets found in dist/ for version ${version} (expected SerialUI-${version}-*.zip or *.tar.gz)." >&2
      exit 2
    fi
  fi

  notes="$(release_notes_from_changelog "${version}")"
  if [[ -n "${notes}" ]]; then
    notes_args=(--notes "${notes}")
  else
    notes_args=(--generate-notes)
  fi

  if [[ "${with_assets}" -eq 1 ]]; then
    gh_no_env_token release create "${tag}" \
      "${assets[@]}" \
      --title "${tag}" \
      "${notes_args[@]}"
  else
    gh_no_env_token release create "${tag}" \
      --title "${tag}" \
      "${notes_args[@]}"
  fi

  echo "Created GitHub release ${tag}"
  if [[ "${with_assets}" -eq 1 ]]; then
    for asset in "${assets[@]}"; do
      echo "  asset: ${asset}"
    done
  fi
}

release_notes_from_changelog() {
  local version="$1"

  if [[ ! -f "CHANGELOG.md" ]]; then
    return 0
  fi

  "${PYTHON_BIN}" - "${version}" <<'PY'
import re
import sys
from pathlib import Path

version = sys.argv[1]
text = Path("CHANGELOG.md").read_text(encoding="utf-8")
heading = re.compile(r"^##\s+(?:\[" + re.escape(version) + r"\]|" + re.escape(version) + r")(?:\s|$).*", re.MULTILINE)
match = heading.search(text)
if not match:
    raise SystemExit(0)

next_heading = re.search(r"^##\s+", text[match.end():], re.MULTILINE)
end = match.end() + next_heading.start() if next_heading else len(text)
notes = text[match.end():end].strip()
if notes:
    print(notes)
PY
}

upload_release_assets() {
  local version="$1"
  local tag="${version}"
  local assets=()
  local upload_assets=()
  local asset
  local asset_name

  require_cmd gh
  require_dir "dist"

  if ! gh_no_env_token auth status >/dev/null 2>&1; then
    echo "Error: gh is not authenticated. Run: gh auth login" >&2
    exit 2
  fi

  if ! gh_no_env_token release view "${tag}" >/dev/null 2>&1; then
    echo "Error: GitHub release ${tag} does not exist." >&2
    exit 2
  fi

  collect_release_assets "${version}" assets
  if [[ "${#assets[@]}" -eq 0 ]]; then
    echo "Error: no uploadable assets found in dist/ for version ${version} (expected SerialUI-${version}-*.zip or *.tar.gz)." >&2
    exit 2
  fi

  for asset in "${assets[@]}"; do
    asset_name="$(basename "${asset}")"
    if gh_no_env_token release view "${tag}" --json assets --jq ".assets[].name" | grep -Fxq "${asset_name}"; then
      echo "Skipping existing release asset: ${asset_name}"
    else
      upload_assets+=("${asset}")
    fi
  done

  if [[ "${#upload_assets[@]}" -eq 0 ]]; then
    echo "All ${#assets[@]} asset(s) already exist on release ${tag}; nothing to upload."
    return 0
  fi

  gh_no_env_token release upload "${tag}" "${upload_assets[@]}"
  echo "Uploaded ${#upload_assets[@]} asset(s) to release ${tag}"
}

usage() {
  cat <<'EOF'
Usage:
  scripts/release.sh [options]

Options:
  --build-executable       Build executable/package via scripts/build_executable.sh.
                           Alias: --build-c-executable, -build-executable
  --build-c-accelerated    Build C-accelerated helpers parser extension in-place,
                           build wheel, and install line_parsers into active env.
                           Alias: -build-c-accelerated
  --update-ankerl          Update ankerl headers used by helpers/line_parsers
                           (unordered_dense.h and companion headers such as stl.h)
                           from helpers/line_parsers/ankerl submodule.
                           This does not trigger any build.
  --commit-msg "message"   Commit message (default: "release: <version>").
                           Alias: -commit-msg "message"
  --commit                 Stage + commit build/release files.
                           Alias: -commit
  --tag                    Create git tag "<version>".
                           Alias: -tag
  --push                   Push commit and current release tag only.
                           Alias: -push
  --release, -release      Create GitHub release and upload compressed assets from dist/ (*.zip, *.tar.gz).
                           If tag "<version>" is missing: implies --build-executable, --tag, --push.
                           If tag "<version>" exists: release-only mode (no rebuild/tag/push).
  --create-release         Create GitHub release for existing pushed tag "<version>" only.
                           Never builds, tags, or pushes, and does not upload assets.
                           Use --upload-assets separately if desired.
                           Therefore does not trigger tag-push workflows.
                           Alias: --createrelease, -create-release, -createrelease
  --upload-assets          Upload additional dist/*.tar.gz and dist/*.zip to existing GitHub release.
                           Alias: -upload-assets
  --clean                  Remove build artifacts before build.
                           Alias: -clean
  -h, --help               Show this help.

Notes:
  - Runs from repository root.
  - Release version is read from config.py (VERSION).
  - --build-executable delegates to scripts/build_executable.sh.
    and creates dist/SerialUI-<version>-<os>-<arch>.zip.
  - --release requires GitHub CLI (gh) authentication.
  - Git and gh commands run with GITHUB_TOKEN and GH_TOKEN unset so stale
    environment tokens do not override stored SSH/browser authentication.
  - --release and --upload-assets only use compressed files already present in dist/.
  - POSIX shell convention is --long-option; single-dash aliases are accepted for parity with PowerShell.
EOF
}

COMMIT_MSG=""
DO_BUILD_EXECUTABLE=0
DO_BUILD_C_ACCELERATED=0
DO_UPDATE_ANKERL=0
DO_COMMIT=0
DO_TAG=0
DO_PUSH=0
DO_RELEASE=0
DO_CREATE_RELEASE=0
DO_UPLOAD_ASSETS=0
DO_CLEAN=0
USER_SET_BUILD_EXECUTABLE=0
USER_SET_TAG=0
USER_SET_PUSH=0
RELEASE_ONLY_MODE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build-executable|--build-c-executable|-build-executable|-BuildExecutable|-BuildCExecutable) DO_BUILD_EXECUTABLE=1; USER_SET_BUILD_EXECUTABLE=1; shift ;;
    --build-c-accelerated|-build-c-accelerated|-BuildCAccelerated) DO_BUILD_C_ACCELERATED=1; shift ;;
    --update-ankerl|-update-ankerl|-UpdateAnkerl) DO_UPDATE_ANKERL=1; shift ;;
    --commit-msg|-commit-msg|-CommitMsg) COMMIT_MSG="${2:-}"; shift 2 ;;
    --commit|-commit|-Commit) DO_COMMIT=1; shift ;;
    --tag|-tag|-Tag) DO_TAG=1; USER_SET_TAG=1; shift ;;
    --push|-push|-Push) DO_PUSH=1; USER_SET_PUSH=1; shift ;;
    --release|-release|-Release) DO_RELEASE=1; shift ;;
    --create-release|--createrelease|-create-release|-createrelease|-CreateRelease) DO_CREATE_RELEASE=1; shift ;;
    --upload-assets|-upload-assets|-UploadAssets) DO_UPLOAD_ASSETS=1; shift ;;
    --clean|-clean|-Clean) DO_CLEAN=1; shift ;;
    -h|--help|-help|-Help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 2 ;;
  esac
done

require_file "config.py"

PACKAGE_VERSION="$(project_version)"
if [[ -z "${PACKAGE_VERSION}" ]]; then
  echo "Error: config.py did not provide VERSION." >&2
  exit 2
fi
validate_version_format "${PACKAGE_VERSION}"
echo "Release version: ${PACKAGE_VERSION}"

if [[ "${DO_RELEASE}" -eq 1 ]]; then
  if git_no_env_token rev-parse -q --verify "refs/tags/${PACKAGE_VERSION}" >/dev/null 2>&1; then
    if [[ "${USER_SET_BUILD_EXECUTABLE}" -eq 0 && "${USER_SET_TAG}" -eq 0 && "${USER_SET_PUSH}" -eq 0 ]]; then
      RELEASE_ONLY_MODE=1
      DO_BUILD_EXECUTABLE=0
      DO_TAG=0
      DO_PUSH=0
      echo "Tag ${PACKAGE_VERSION} already exists; running release-only mode."
    fi
  else
    if [[ "${USER_SET_BUILD_EXECUTABLE}" -eq 0 ]]; then
      DO_BUILD_EXECUTABLE=1
    fi
    if [[ "${USER_SET_TAG}" -eq 0 ]]; then
      DO_TAG=1
    fi
    if [[ "${USER_SET_PUSH}" -eq 0 ]]; then
      DO_PUSH=1
    fi
  fi
fi

if [[ "${DO_CREATE_RELEASE}" -eq 1 ]]; then
  DO_RELEASE=1
  RELEASE_ONLY_MODE=1
  DO_BUILD_EXECUTABLE=0
  DO_TAG=0
  DO_PUSH=0

  if ! git_no_env_token rev-parse -q --verify "refs/tags/${PACKAGE_VERSION}" >/dev/null 2>&1; then
    echo "Error: --create-release requires existing local tag ${PACKAGE_VERSION}." >&2
    echo "Run: git tag ${PACKAGE_VERSION} && git push origin refs/tags/${PACKAGE_VERSION}" >&2
    exit 2
  fi

  CURRENT_BRANCH="$(git_no_env_token branch --show-current)"
  CHECK_REMOTE="$(git_no_env_token config --get "branch.${CURRENT_BRANCH}.remote" || true)"
  if [[ -z "${CHECK_REMOTE}" ]]; then
    CHECK_REMOTE="origin"
  fi
  if ! git_no_env_token ls-remote --exit-code --tags "${CHECK_REMOTE}" "refs/tags/${PACKAGE_VERSION}" >/dev/null 2>&1; then
    echo "Error: --create-release requires tag ${PACKAGE_VERSION} to be pushed to ${CHECK_REMOTE}." >&2
    echo "Run: git push ${CHECK_REMOTE} refs/tags/${PACKAGE_VERSION}" >&2
    exit 2
  fi
fi

if [[ "${DO_CLEAN}" -eq 1 ]]; then
  rm -rf build dist ./*.egg-info ./*.egg .pytest_cache
  rm -rf helpers/build helpers/dist helpers/*.egg-info helpers/.eggs
fi

if [[ "${DO_UPDATE_ANKERL}" -eq 1 ]]; then
  require_file "scripts/update_ankerl.sh"
  "${SCRIPT_DIR}/update_ankerl.sh"
fi

UPDATE_ONLY_MODE=0
if [[ "${DO_UPDATE_ANKERL}" -eq 1 \
   && "${DO_BUILD_EXECUTABLE}" -eq 0 \
   && "${DO_BUILD_C_ACCELERATED}" -eq 0 \
   && "${DO_RELEASE}" -eq 0 \
   && "${DO_UPLOAD_ASSETS}" -eq 0 \
   && "${DO_COMMIT}" -eq 0 \
   && "${DO_TAG}" -eq 0 \
   && "${DO_PUSH}" -eq 0 ]]; then
  UPDATE_ONLY_MODE=1
fi

if [[ "${UPDATE_ONLY_MODE}" -eq 1 ]]; then
  echo "Update-only mode: skipped helper/executable build steps."
  echo "Release script completed."
  exit 0
fi

REQUESTED_NONBUILD_ACTION=0
if [[ "${DO_COMMIT}" -eq 1 \
   || "${DO_TAG}" -eq 1 \
   || "${DO_PUSH}" -eq 1 \
   || "${DO_RELEASE}" -eq 1 \
   || "${DO_CREATE_RELEASE}" -eq 1 \
   || "${DO_UPLOAD_ASSETS}" -eq 1 \
   || "${DO_CLEAN}" -eq 1 ]]; then
  REQUESTED_NONBUILD_ACTION=1
fi

DO_BUILD_HELPERS=0
if [[ "${DO_BUILD_EXECUTABLE}" -eq 1 ]]; then
  DO_BUILD_HELPERS=0
elif [[ "${DO_BUILD_C_ACCELERATED}" -eq 1 ]]; then
  DO_BUILD_HELPERS=1
elif [[ "${REQUESTED_NONBUILD_ACTION}" -eq 0 && "${DO_UPDATE_ANKERL}" -eq 0 ]]; then
  # Keep legacy default: `release.sh` with no options builds helper wheel.
  DO_BUILD_HELPERS=1
fi

if [[ "${DO_BUILD_EXECUTABLE}" -eq 1 ]]; then
  require_file "scripts/build_executable.sh"
  BUILD_EXEC_ARGS=(PYTHON_BIN="${PYTHON_BIN}" BUILD_C_ACCEL=0)
  if [[ "${DO_BUILD_C_ACCELERATED}" -eq 1 ]]; then
    BUILD_EXEC_ARGS=(PYTHON_BIN="${PYTHON_BIN}" BUILD_C_ACCEL=1)
  fi
  env "${BUILD_EXEC_ARGS[@]}" "${SCRIPT_DIR}/build_executable.sh"
elif [[ "${DO_BUILD_HELPERS}" -eq 1 || "${DO_BUILD_C_ACCELERATED}" -eq 1 ]]; then
  require_file "helpers/setup.py"
  pushd "helpers" >/dev/null

  if [[ "${DO_BUILD_C_ACCELERATED}" -eq 1 ]]; then
    echo "Building C-accelerated parser extension in helpers/..."
    rm -rf build ./*.egg-info .eggs
    PYTHONWARNINGS="${PYTHONWARNINGS:-ignore::FutureWarning}" "${PYTHON_BIN}" setup.py build_ext --inplace -v
  fi

  if "${PYTHON_BIN}" -m build --help >/dev/null 2>&1; then
    PYTHONWARNINGS="${PYTHONWARNINGS:-ignore::FutureWarning}" "${PYTHON_BIN}" -m build --no-isolation
  else
    echo "Warning: python build package not found; falling back to pip wheel." >&2
    PYTHONWARNINGS="${PYTHONWARNINGS:-ignore::FutureWarning}" "${PYTHON_BIN}" -m pip wheel . --no-deps --no-build-isolation -w dist
  fi

  shopt -s nullglob
  WHEELS=(dist/*.whl)
  shopt -u nullglob
  if [[ "${#WHEELS[@]}" -eq 0 ]]; then
    echo "Error: build completed but no wheel found in helpers/dist/." >&2
    exit 2
  fi
  WHEEL_PATH="$(ls -t dist/*.whl | head -n1)"
  echo "Built wheel: helpers/${WHEEL_PATH}"

  if [[ "${DO_BUILD_C_ACCELERATED}" -eq 1 ]]; then
    "${PYTHON_BIN}" -m pip install --force-reinstall --no-deps "${WHEEL_PATH}"
    echo "Installed wheel into active environment: helpers/${WHEEL_PATH}"
  fi

  popd >/dev/null
fi

if [[ "${DO_COMMIT}" -eq 1 ]]; then
  if [[ -z "${COMMIT_MSG}" ]]; then
    COMMIT_MSG="release: ${PACKAGE_VERSION}"
  fi
  git_no_env_token add -A
  git_no_env_token commit -m "${COMMIT_MSG}"
fi

if [[ "${DO_TAG}" -eq 1 ]]; then
  git_no_env_token tag "${PACKAGE_VERSION}"
fi

if [[ "${DO_PUSH}" -eq 1 ]]; then
  CURRENT_BRANCH="$(git_no_env_token branch --show-current)"
  PUSH_REMOTE="$(git_no_env_token config --get "branch.${CURRENT_BRANCH}.remote" || true)"
  if [[ -z "${PUSH_REMOTE}" ]]; then
    PUSH_REMOTE="origin"
  fi

  git_no_env_token push
  git_no_env_token push "${PUSH_REMOTE}" "refs/tags/${PACKAGE_VERSION}"
fi

if [[ "${DO_RELEASE}" -eq 1 ]]; then
  RELEASE_WITH_ASSETS=1
  if [[ "${DO_CREATE_RELEASE}" -eq 1 ]]; then
    RELEASE_WITH_ASSETS=0
  fi
  create_github_release "${PACKAGE_VERSION}" "${RELEASE_WITH_ASSETS}" "${DO_CREATE_RELEASE}"
fi

if [[ "${DO_UPLOAD_ASSETS}" -eq 1 ]]; then
  upload_release_assets "${PACKAGE_VERSION}"
fi

echo "Release script completed."
