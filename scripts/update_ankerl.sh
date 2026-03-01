#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SUBMODULE_PATH="helpers/line_parsers/ankerl"
SRC_BASE_REL="${SUBMODULE_PATH}/include/ankerl"
DST_BASE_REL="helpers/line_parsers"
REQUIRED_HEADERS=("unordered_dense.h")
OPTIONAL_HEADERS=("stl.h")

echo "Syncing ankerl header..."

echo "Updating ankerl submodule from upstream..."
git -C "${ROOT_DIR}" submodule sync -- "${SUBMODULE_PATH}"
if ! git -C "${ROOT_DIR}" submodule update --init --remote --depth 1 -- "${SUBMODULE_PATH}"; then
  echo "Warning: remote submodule refresh failed; using local submodule state if available." >&2
  # Fallback for offline environments: ensure submodule working tree is at least initialized.
  git -C "${ROOT_DIR}" submodule update --init --depth 1 -- "${SUBMODULE_PATH}" || true
fi

UPDATED=0
for header in "${REQUIRED_HEADERS[@]}"; do
  SRC_REL="${SRC_BASE_REL}/${header}"
  DST_REL="${DST_BASE_REL}/${header}"
  SRC="${ROOT_DIR}/${SRC_REL}"
  DST="${ROOT_DIR}/${DST_REL}"

  if [[ ! -f "${SRC}" ]]; then
    echo "Error: source header missing after submodule update: ${SRC_REL}" >&2
    exit 1
  fi

  mkdir -p "$(dirname "${DST}")"

  if [[ -f "${DST}" ]] && cmp -s "${SRC}" "${DST}"; then
    echo "${header} already up to date."
    continue
  fi

  cp "${SRC}" "${DST}"
  echo "Updated: ${DST_REL}"
  UPDATED=1
done

for header in "${OPTIONAL_HEADERS[@]}"; do
  SRC_REL="${SRC_BASE_REL}/${header}"
  DST_REL="${DST_BASE_REL}/${header}"
  SRC="${ROOT_DIR}/${SRC_REL}"
  DST="${ROOT_DIR}/${DST_REL}"

  if [[ ! -f "${SRC}" ]]; then
    echo "Optional header not present in current ankerl version: ${SRC_REL}"
    continue
  fi

  mkdir -p "$(dirname "${DST}")"

  if [[ -f "${DST}" ]] && cmp -s "${SRC}" "${DST}"; then
    echo "${header} already up to date."
    continue
  fi

  cp "${SRC}" "${DST}"
  echo "Updated: ${DST_REL}"
  UPDATED=1
done

if [[ "${UPDATED}" -eq 0 ]]; then
  echo "All synced ankerl headers already up to date."
fi
