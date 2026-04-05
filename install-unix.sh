#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck disable=SC1091
source "$SCRIPT_DIR/portable-ai.conf"

detect_platform() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"

  case "$os" in
    Darwin)
      PLATFORM_ID="macos"
      PLATFORM_DIR="$SCRIPT_DIR/ollama/macos"
      ARCHIVE_NAME="Ollama-darwin.zip"
      DOWNLOAD_URL="https://github.com/ollama/ollama/releases/latest/download/$ARCHIVE_NAME"
      ;;
    Linux)
      PLATFORM_ID="linux"
      case "$arch" in
        x86_64|amd64)
          ARCHIVE_NAME="ollama-linux-amd64.tgz"
          ;;
        aarch64|arm64)
          ARCHIVE_NAME="ollama-linux-arm64.tgz"
          ;;
        *)
          echo "Unsupported Linux architecture: $arch" >&2
          exit 1
          ;;
      esac
      PLATFORM_DIR="$SCRIPT_DIR/ollama/linux-$arch"
      DOWNLOAD_URL="https://github.com/ollama/ollama/releases/latest/download/$ARCHIVE_NAME"
      ;;
    *)
      echo "Unsupported operating system: $os" >&2
      exit 1
      ;;
  esac
}

prepare_env() {
  export HOME="$SCRIPT_DIR/home/$PLATFORM_ID"
  export XDG_DATA_HOME="$HOME/.local/share"
  export XDG_CONFIG_HOME="$HOME/.config"
  export XDG_STATE_HOME="$HOME/.local/state"
  export OLLAMA_MODELS="$SCRIPT_DIR/ollama/models"
  export OLLAMA_HOST

  mkdir -p "$HOME" "$XDG_DATA_HOME" "$XDG_CONFIG_HOME" "$XDG_STATE_HOME" "$OLLAMA_MODELS" "$SCRIPT_DIR/tmp"
}

ollama_bin() {
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
  local ollama="$1"
  local tries=0
  until "$ollama" list >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [[ "$tries" -ge 30 ]]; then
      echo "Ollama did not become ready in time." >&2
      return 1
    fi
    sleep 1
  done
}

detect_platform
prepare_env

echo "Installing portable Ollama for $PLATFORM_ID into:"
echo "  $PLATFORM_DIR"
mkdir -p "$PLATFORM_DIR"

if ! OLLAMA_BIN="$(ollama_bin)"; then
  ARCHIVE_PATH="$SCRIPT_DIR/tmp/$ARCHIVE_NAME"
  echo "Downloading $ARCHIVE_NAME ..."
  curl -L --fail --progress-bar "$DOWNLOAD_URL" -o "$ARCHIVE_PATH"

  rm -rf "$PLATFORM_DIR"
  mkdir -p "$PLATFORM_DIR"

  case "$ARCHIVE_NAME" in
    *.zip)
      unzip -oq "$ARCHIVE_PATH" -d "$PLATFORM_DIR"
      ;;
    *.tgz)
      tar -xzf "$ARCHIVE_PATH" -C "$PLATFORM_DIR"
      ;;
    *)
      echo "Unsupported archive format: $ARCHIVE_NAME" >&2
      exit 1
      ;;
  esac

  rm -f "$ARCHIVE_PATH"
  OLLAMA_BIN="$(ollama_bin)"
fi

if [[ -z "${OLLAMA_BIN:-}" ]]; then
  echo "Could not locate the portable Ollama binary after extraction." >&2
  exit 1
fi

echo "Using binary:"
echo "  $OLLAMA_BIN"

LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

echo "Starting Ollama temporarily to pull $MODEL_NAME ..."
"$OLLAMA_BIN" serve >"$LOG_DIR/install-ollama.log" 2>&1 &
SERVER_PID=$!
cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

wait_for_server "$OLLAMA_BIN"
"$OLLAMA_BIN" pull "$MODEL_NAME"

echo
echo "Portable Ollama is ready."
echo "Run ./start-unix.sh to start an interactive $MODEL_NAME session."
