#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck disable=SC1091
source "$SCRIPT_DIR/portable-ai.conf"

detect_platform() {
  case "$(uname -s)" in
    Darwin)
      PLATFORM_ID="macos"
      PLATFORM_DIR="$SCRIPT_DIR/ollama/macos"
      ;;
    Linux)
      PLATFORM_ID="linux"
      PLATFORM_DIR="$SCRIPT_DIR/ollama/linux-$(uname -m)"
      ;;
    *)
      echo "Unsupported operating system: $(uname -s)" >&2
      exit 1
      ;;
  esac
}

find_ollama() {
  local candidates=(
    "$PLATFORM_DIR/bin/ollama"
    "$PLATFORM_DIR/ollama"
    "$PLATFORM_DIR/Ollama.app/Contents/Resources/ollama"
    "$PLATFORM_DIR/Ollama.app/Contents/MacOS/Ollama"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

wait_for_server() {
  local tries=0
  until "$OLLAMA_BIN" list >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [[ "$tries" -ge 30 ]]; then
      echo "Ollama did not become ready in time." >&2
      exit 1
    fi
    sleep 1
  done
}

detect_platform

export HOME="$SCRIPT_DIR/home/$PLATFORM_ID"
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_STATE_HOME="$HOME/.local/state"
export OLLAMA_MODELS="$SCRIPT_DIR/ollama/models"
export OLLAMA_HOST

mkdir -p "$HOME" "$XDG_DATA_HOME" "$XDG_CONFIG_HOME" "$XDG_STATE_HOME" "$OLLAMA_MODELS" "$SCRIPT_DIR/logs"

if ! OLLAMA_BIN="$(find_ollama)"; then
  echo "Portable Ollama is not installed for this platform yet."
  echo "Run ./install-unix.sh first."
  exit 1
fi

"$OLLAMA_BIN" serve >"$SCRIPT_DIR/logs/runtime-ollama.log" 2>&1 &
SERVER_PID=$!

cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

wait_for_server

if ! "$OLLAMA_BIN" list | awk '{print $1}' | grep -Fxq "$MODEL_NAME"; then
  echo "Model $MODEL_NAME is not on this drive yet. Pulling it now ..."
  "$OLLAMA_BIN" pull "$MODEL_NAME"
fi

if [[ "$#" -gt 0 ]]; then
  "$OLLAMA_BIN" "$@"
else
  echo "Portable Ollama is running from:"
  echo "  $SCRIPT_DIR"
  echo "Model store:"
  echo "  $OLLAMA_MODELS"
  echo
  echo "Starting chat with $MODEL_NAME ..."
  "$OLLAMA_BIN" run "$MODEL_NAME"
fi
