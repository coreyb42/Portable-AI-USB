from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_settings
from .indexer import index_paths, plain_text_search, semantic_search
from .ollama_runtime import ensure_model, ensure_server, find_ollama_binary, server_running
from .readers import read_path


def _resolve_target(root_dir: Path, raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return (root_dir / path).resolve()


def cmd_browse(args: argparse.Namespace) -> dict:
    settings = load_settings()
    target = _resolve_target(settings.root_dir, args.path)
    entries = []
    for child in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        stat = child.stat()
        entries.append(
            {
                "name": child.name,
                "path": str(child.relative_to(settings.root_dir)) if child.is_relative_to(settings.root_dir) else str(child),
                "type": "directory" if child.is_dir() else "file",
                "size": stat.st_size,
            }
        )
        if len(entries) >= args.limit:
            break
    return {"path": str(target), "entries": entries}


def cmd_search(args: argparse.Namespace) -> dict:
    settings = load_settings()
    target = _resolve_target(settings.root_dir, args.path)
    return {"query": args.query, "results": plain_text_search(target, args.query, args.limit)}


def cmd_read(args: argparse.Namespace) -> dict:
    settings = load_settings()
    target = _resolve_target(settings.root_dir, args.path)
    result = read_path(target)
    payload = {
        "path": result.path,
        "file_type": result.file_type,
        "metadata": result.metadata,
        "text": result.text[: args.max_chars],
    }
    if args.include_sections:
        payload["sections"] = result.sections[: args.max_sections]
    return payload


def cmd_index(args: argparse.Namespace) -> dict:
    settings = load_settings()
    ensure_server(settings)
    ensure_model(settings, settings.embed_model)
    target = _resolve_target(settings.root_dir, args.path)
    return index_paths(settings, target, args.limit)


def cmd_semantic_search(args: argparse.Namespace) -> dict:
    settings = load_settings()
    ensure_server(settings)
    ensure_model(settings, settings.embed_model)
    matches = semantic_search(settings, args.query, args.limit)
    return {
        "query": args.query,
        "results": [
            {
                "path": match.path,
                "score": round(match.score, 6),
                "chunk_index": match.chunk_index,
                "text": match.text,
                "metadata": match.metadata,
            }
            for match in matches
        ],
    }


def cmd_doctor(args: argparse.Namespace) -> dict:
    settings = load_settings()
    payload = {
        "root_dir": str(settings.root_dir),
        "ollama_host": settings.ollama_host,
        "model_name": settings.model_name,
        "embed_model": settings.embed_model,
        "index_db": str(settings.index_db),
        "server_running": server_running(settings),
    }
    try:
        payload["ollama_binary"] = str(find_ollama_binary(settings))
    except FileNotFoundError as exc:
        payload["ollama_binary_error"] = str(exc)
        return payload

    if args.check_server:
        try:
            ensure_server(settings)
            payload["server_check"] = "ok"
        except Exception as exc:
            payload["server_check"] = "failed"
            payload["server_error"] = str(exc)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Portable USB AI file tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    browse = subparsers.add_parser("browse", help="List files/directories.")
    browse.add_argument("path", nargs="?", default=".")
    browse.add_argument("--limit", type=int, default=200)
    browse.set_defaults(func=cmd_browse)

    search = subparsers.add_parser("search", help="Search paths and file text.")
    search.add_argument("query")
    search.add_argument("path", nargs="?", default=".")
    search.add_argument("--limit", type=int, default=20)
    search.set_defaults(func=cmd_search)

    read = subparsers.add_parser("read", help="Read a text, PDF, or EPUB file.")
    read.add_argument("path")
    read.add_argument("--max-chars", type=int, default=12000)
    read.add_argument("--include-sections", action="store_true")
    read.add_argument("--max-sections", type=int, default=20)
    read.set_defaults(func=cmd_read)

    index = subparsers.add_parser("index", help="Build semantic index for supported files.")
    index.add_argument("path", nargs="?", default=".")
    index.add_argument("--limit", type=int)
    index.set_defaults(func=cmd_index)

    semantic = subparsers.add_parser("semantic-search", help="Query the semantic index.")
    semantic.add_argument("query")
    semantic.add_argument("--limit", type=int, default=5)
    semantic.set_defaults(func=cmd_semantic_search)

    doctor = subparsers.add_parser("doctor", help="Inspect portable tool and Ollama runtime status.")
    doctor.add_argument("--check-server", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = args.func(args)
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
