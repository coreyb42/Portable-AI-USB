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

## Python File Tools

The repo now includes a portable Python toolkit intended for LLM-facing file access on the USB drive:

- `browse`: directory listing with metadata
- `search`: path and text search across supported files
- `read`: structured reader for text, PDF, and EPUB files
- `index`: semantic chunk indexing into a SQLite database on the drive
- `semantic-search`: embedding search against the indexed chunks
- `ask`: one-shot Ollama agent with tool calling
- `chat`: interactive Ollama agent with tool calling

Setup:

```bash
chmod +x install-python-tools.sh usb-tools
./install-python-tools.sh
```

Examples:

```bash
./usb-tools browse
./usb-tools browse ai --recursive --max-depth 1
./usb-tools search "portable ollama"
./usb-tools read ai/Portable-AI-USB/README.md
./usb-tools doctor
./usb-tools doctor --check-server
./usb-tools index
./usb-tools semantic-search "Where is the Ollama model store configured?"
./usb-tools ask "Find the Ollama-related project on this drive and summarize how it works."
./usb-tools chat
```

Implementation notes:

- The Python tools keep state under `.portable_tools/` on the USB drive
- By default, tool paths resolve relative to `../..` from this repo checkout, which is treated as the drive root
- Semantic search uses the local Ollama installation from this repo, not a host install
- The `ask` and `chat` commands bind Python tool functions directly into Ollama's tool-calling loop
- The embedding model defaults to `nomic-embed-text` and is configured in `portable-ai.conf`
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
