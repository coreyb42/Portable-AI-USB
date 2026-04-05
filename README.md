# Portable Ollama USB

Portable Ollama install for an external drive, with a shared model store and launchers for Windows, macOS, and Linux.

The default model is `gemma4:e4b`, pulled from the official Ollama library. As of April 5, 2026, Ollama lists `gemma4:e4b` as the current edge-friendly 4B Gemma 4 variant: https://ollama.com/library/gemma4

## What This Fork Does

- Keeps Ollama binaries on the external drive instead of installing system-wide
- Keeps model data on the external drive with `OLLAMA_MODELS`
- Uses per-platform portable home/config directories on the drive for macOS and Linux
- Defaults to `gemma4:e4b`
- Keeps downloaded runtimes and models out of git via `.gitignore`

## Requirements

- exFAT is still the best filesystem choice for cross-platform use
- At least 20 GB free space is realistic for `gemma4:e4b` plus platform runtimes
- Internet access is only needed during install and model download

## Setup

### Windows

1. Run `install.bat`
2. Wait for Ollama, AnythingLLM, and `gemma4:e4b` to download
3. Start with `start-windows.bat`

### macOS or Linux

1. Run `chmod +x install-unix.sh start-unix.sh start-linux.sh start-mac.command`
2. Run `./install-unix.sh`
3. Start with `./start-unix.sh`

Shortcuts:

- macOS: double-click `start-mac.command`
- Linux: run `./start-linux.sh`

## Usage

`start-unix.sh` starts the Ollama server from the drive, ensures `gemma4:e4b` exists locally, and then opens an interactive `ollama run gemma4:e4b` session.

You can also pass direct Ollama commands through the launcher:

```bash
./start-unix.sh list
./start-unix.sh ps
./start-unix.sh run gemma4:e4b
```

## Python Agent

The repo now includes a portable Python Ollama agent that can use filesystem tools against the USB drive:

- `ask`: one-shot Ollama agent with tool calling
- `chat`: interactive Ollama agent with tool calling
- `maint`: maintenance commands for the file catalog and semantic index

Setup:

```bash
chmod +x install-python-tools.sh usb-tools start-agent.sh start-agent.command
./install-python-tools.sh
```

Examples:

```bash
./start-agent.sh
./usb-tools doctor
./usb-tools doctor --check-server
./usb-tools maint refresh
./usb-tools maint stats
./usb-tools maint duplicates
./usb-tools maint sample --category medical
./usb-tools ask "Find the Ollama-related project on this drive and summarize how it works."
./usb-tools chat
```

Launch shortcuts:

- macOS: double-click `start-agent.command`
- Terminal: run `./start-agent.sh`
- One-shot prompt: run `./usb-tools ask "your prompt"`

Implementation notes:

- The Python agent keeps its semantic index and working state under `.portable_tools/` on the USB drive
- By default, tool paths resolve relative to `../..` from this repo checkout, which is treated as the drive root
- Semantic search uses the local Ollama installation from this repo, not a host install
- The agent internally exposes browse, search, read, exact quote location, index refresh, and semantic-search tools to the model
- Catalog metadata includes filename, top-level collection, derived category, derived genre, and path-derived tags
- Agent retrieval tools can filter on category, genre, tag, relative path substring, and filename substring
- Quote and semantic results include file and page/section/line-style location metadata when available
- `maint refresh` populates a SQLite-backed library catalog and semantic index, deduping files by content hash so duplicate sources are not embedded twice
- `maint refresh` now prints per-file progress and is resumable because it commits work file-by-file and skips unchanged files on later runs
- The embedding model defaults to `qwen3-embedding:4b` and is configured in `portable-ai.conf`
- `doctor --check-server` validates that the portable Ollama runtime can actually start on the current machine before you spend time indexing

## Portable Layout

```text
Portable-AI-USB/
├── install.bat
├── install-core.ps1
├── install-python-tools.sh
├── install-unix.sh
├── python-tools/
├── start-windows.bat
├── start-mac.command
├── start-linux.sh
├── start-unix.sh
├── portable-ai.conf
├── start-agent.command
├── start-agent.sh
├── usb-tools
├── ollama/
│   ├── macos/
│   ├── linux-<arch>/
│   └── models/
├── .portable_tools/
├── home/
└── logs/
```

## Notes

- macOS support depends on Ollama's own platform support. Current Ollama docs list macOS 14+ and Apple Silicon or x86 support: https://docs.ollama.com/macos
- Linux tarballs are large because Ollama ships its runtime dependencies with them
- The repo does not currently provide a Linux GUI wrapper like AnythingLLM; the Unix path is Ollama CLI/API first

## License

MIT. See [LICENSE](LICENSE).
