#!/usr/bin/env bash
set -euo pipefail

VENV_DIR="$HOME/Python/serialui"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but was not found in PATH." >&2
  exit 1
fi

mkdir -p "$HOME/Python"

venv_existed=0
if [ -d "$VENV_DIR" ]; then
  venv_existed=1
else
  python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip

COMMON_PACKAGES=(
  pyqt6
  pyqtgraph
  markdown
  bleak
  numpy
  scipy
  numba
  fastplotlib
  PyOpenGL
  pybind11
  setuptools
  cobs
  tamp
)

OS_PACKAGES=()
case "$(uname -s)" in
  Linux*)
    OS_PACKAGES+=(pyudev)
    ;;
  Darwin*)
    # No extra USB notifier package required on macOS.
    ;;
  MINGW*|MSYS*|CYGWIN*|Windows_NT)
    OS_PACKAGES+=(wmi)
    ;;
  *)
    echo "Unrecognized OS for USB notifier package; skipping wmi/pyudev." >&2
    ;;
esac

install_args=(-m pip install)
if [ "$venv_existed" -eq 1 ]; then
  install_args+=(--upgrade)
fi

python "${install_args[@]}" "${COMMON_PACKAGES[@]}" "${OS_PACKAGES[@]}"

echo ""
echo "Virtual environment ready: $VENV_DIR"
echo "Python: $(command -v python)"

# If sourced, keep activation in the current shell.
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
  echo "Virtual environment activated in current shell."
  return 0 2>/dev/null || exit 0
fi

# If executed, open an interactive shell that activates on startup so prompt updates.
if [ -n "${VIRTUAL_ENV_DISABLE_PROMPT:-}" ] && [ "${VIRTUAL_ENV_DISABLE_PROMPT}" != "0" ]; then
  echo "Note: VIRTUAL_ENV_DISABLE_PROMPT is set; prompt prefix may be hidden."
fi

shell_path="${SHELL:-/bin/bash}"
shell_name="$(basename "$shell_path")"

if [ "$shell_name" = "bash" ]; then
  echo "Opening a new bash shell with the virtual environment activated..."
  exec bash --rcfile <(
    printf '%s\n' \
      '[[ -f ~/.bashrc ]] && source ~/.bashrc' \
      "source \"$VENV_DIR/bin/activate\""
  ) -i
elif [ "$shell_name" = "zsh" ]; then
  echo "Opening a new zsh shell with the virtual environment activated..."
  zdotdir_tmp="$(mktemp -d "${TMPDIR:-/tmp}/serialui-zdot.XXXXXX")"
  cat > "$zdotdir_tmp/.zshrc" <<EOF
[[ -f ~/.zshrc ]] && source ~/.zshrc
source "$VENV_DIR/bin/activate"
EOF
  exec env ZDOTDIR="$zdotdir_tmp" zsh -i
else
  echo "Opening a new $shell_name shell with the virtual environment activated..."
  exec "$shell_path" -i
fi
