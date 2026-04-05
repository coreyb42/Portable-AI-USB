# AGENTS

## Purpose

This project turns the external drive into a portable local AI workspace built around Ollama.

The current goals are:

- Keep the Ollama runtime and model data on the drive
- Run from macOS and Linux without depending on a host install
- Provide an agent CLI that can inspect and reason over the files stored on the drive
- Maintain a local catalog and semantic index of the library on the drive

## High-Level Setup

- Ollama binaries live under `ollama/`
- Ollama model data lives under `ollama/models/`
- Portable home/config state lives under `home/`
- Python agent state lives under `.portable_tools/`
- The agent defaults its filesystem scope to `../..` from this repo, which is the drive root

## Agent Model

- Interactive entrypoint: `./start-agent.sh`
- One-shot entrypoint: `./usb-tools ask "..."`
- Maintenance entrypoint: `./usb-tools maint ...`

The user-facing CLI is agent-first.

Internal tools are exposed to the model through Ollama tool calling rather than as user-facing shell commands.

## Library Indexing

The SQLite database under `.portable_tools/semantic_index.sqlite3` stores:

- High-level file catalog records
- Duplicate tracking by content hash
- Semantic chunks with location metadata

The maintenance flow is:

1. Run `./usb-tools maint refresh`
2. This scans supported files, dedupes by content hash, updates file metadata, and stores embeddings
3. Inspect with `./usb-tools maint stats` or `./usb-tools maint duplicates`

## File Search Expectations

The agent should be able to:

- Browse the drive
- Search by exact text
- Read text, PDF, and EPUB files
- Locate exact quotes with file and page/section/line references
- Run semantic search over indexed passages with file and location metadata

## Development Notes

- Prefer keeping all state on the drive
- Avoid host-specific absolute paths in persisted metadata except where required for runtime detection
- Treat duplicate content as a catalog concern and avoid embedding identical sources more than once
