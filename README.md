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

## Portable Layout

```text
Portable-AI-USB/
├── install.bat
├── install-core.ps1
├── install-unix.sh
├── start-windows.bat
├── start-mac.command
├── start-linux.sh
├── start-unix.sh
├── portable-ai.conf
├── ollama/
│   ├── macos/
│   ├── linux-<arch>/
│   └── models/
├── home/
└── logs/
```

## Notes

- macOS support depends on Ollama's own platform support. Current Ollama docs list macOS 14+ and Apple Silicon or x86 support: https://docs.ollama.com/macos
- Linux tarballs are large because Ollama ships its runtime dependencies with them
- The repo does not currently provide a Linux GUI wrapper like AnythingLLM; the Unix path is Ollama CLI/API first

## License

MIT. See [LICENSE](LICENSE).
