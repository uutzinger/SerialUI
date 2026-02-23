#!/usr/bin/env bash
set -euo pipefail

# Configuration
COMMENT_COL=80                      # target inline comment column for fixed_comment_col.py
HASH_COL=140                        # end column for '#' rule lines
EQUAL_COL=80                        # end column for '=' rule lines
DASH_LEN=40                         # length for '-' rule lines
TABSIZE=8                           # tabsize for header rules script
FIXED_COMMENT_COL="fixed_comment_col.py"
FIX_HEADER_RULES="fix_header_rules.py"

# File globs to process (expand/adjust as needed)
FILE_GLOBS=(
  "SerialUI.py"
  "helpers/*.py"
)

MODE="fix"   # default
if [[ "${1:-}" == "--check" ]]; then
  MODE="check"
  shift || true
fi

# Resolve repository root (directory containing this script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

has_changes=0

reformat_one() {
  local file="$1"
  [[ -f "$file" ]] || return 0

  # Create a backup once
  if [[ ! -f "${file}.bak" ]]; then
    cp -p -- "$file" "${file}.bak"
    echo "[backup] ${file}.bak created"
  fi

  local tmp1 tmp2
  tmp1="$(mktemp)"
  tmp2="$(mktemp)"

  # Step 1: inline comment alignment (exact mode already in that script)
  python3 "$SCRIPT_DIR/$FIXED_COMMENT_COL" --mode fix --col "$COMMENT_COL" "$file" > "$tmp1"

  # Step 2: header rule normalization
  # Mix column targets and length target as requested
  python3 "$SCRIPT_DIR/$FIX_HEADER_RULES" \
    --mode fix \
    --col-hash "$HASH_COL" \
    --col-equal "$EQUAL_COL" \
    --len-dash "$DASH_LEN" \
    --tabsize "$TABSIZE" \
    "$tmp1" > "$tmp2"

  if cmp -s "$file" "$tmp2"; then
    echo "[unchanged] $file"
  else
    if [[ "$MODE" == "check" ]]; then
      echo "[diff] $file" >&2
      # Show a unified diff to stderr
      diff -u --label "orig/$file" --label "new/$file" "$file" "$tmp2" >&2 || true
      has_changes=1
    else
      mv "$tmp2" "$file"
      echo "[updated] $file"
    fi
  fi

  rm -f "$tmp1" "$tmp2" 2>/dev/null || true
}

# Expand globs
FILES=()
for g in "${FILE_GLOBS[@]}"; do
  # shellcheck disable=SC2046
  for f in $g; do
    [[ -e "$f" ]] && FILES+=("$f")
  done
done

if [[ ${#FILES[@]} -eq 0 ]]; then
  echo "No files matched. Adjust FILE_GLOBS." >&2
  exit 0
fi

for f in "${FILES[@]}"; do
  reformat_one "$f"
done

if [[ "$MODE" == "check" ]]; then
  if [[ $has_changes -ne 0 ]]; then
    echo -e "\nFormatting differences found." >&2
    exit 1
  else
    echo "All files already formatted."
  fi
fi
