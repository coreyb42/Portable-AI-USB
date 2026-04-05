from __future__ import annotations

import argparse
import json

from ollama import Client, ResponseError

from .agent import tool_map, tool_result_content
from .config import load_settings
from .fsops import resolve_in_scope
from .indexer import catalog_sample, catalog_stats, duplicate_sources, refresh_library
from .ollama_runtime import ensure_model, ensure_server, find_ollama_binary, server_running


def _format_tool_args(arguments: dict, max_length: int = 180) -> str:
    raw = json.dumps(arguments, ensure_ascii=True, sort_keys=True)
    if len(raw) <= max_length:
        return raw
    return f"{raw[: max_length - 3]}..."


def _print_tool_event(name: str, arguments: dict, result: dict) -> None:
    print(f"\n[tool] {name} {_format_tool_args(arguments)}")
    if "error" in result:
        print(f"[tool] {name} failed: {result['error']}")
        return

    if name == "browse":
        count = len(result.get("entries", []))
        print(f"[tool] {name} ok: {count} entries from {result.get('path', '.')}")
        return
    if name == "search":
        count = len(result.get("results", []))
        print(f"[tool] {name} ok: {count} matches")
        return
    if name == "read":
        text_len = len(result.get("text", ""))
        print(f"[tool] {name} ok: {result.get('path')} ({text_len} chars)")
        return
    if name == "index":
        print(
            f"[tool] {name} ok: updated={result.get('updated_files', 0)} "
            f"unchanged={result.get('unchanged_files', 0)} duplicates={result.get('duplicate_files', 0)}"
        )
        return
    if name == "locate_quote":
        count = len(result.get("results", []))
        print(f"[tool] {name} ok: {count} exact matches")
        return
    if name == "semantic_search":
        count = len(result.get("results", []))
        print(f"[tool] {name} ok: {count} semantic matches")
        return
    print(f"[tool] {name} ok")


def cmd_doctor(args: argparse.Namespace) -> dict:
    settings = load_settings()
    payload = {
        "root_dir": str(settings.root_dir),
        "scope_root": str(settings.scope_root),
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


def _agent_system_prompt(scope_root: str) -> str:
    return (
        "You are a local file assistant running against an external drive. "
        f"Your default filesystem scope is the drive root at {scope_root}. "
        "Use tools instead of guessing when file contents or structure matter. "
        "Prefer browse for discovery, search for keyword matching, read for direct inspection, "
        "index before semantic_search if the semantic index may be stale or missing. "
        "When citing files, mention relative paths from the drive root."
    )


def _run_agent_turn(client: Client, model: str, messages: list[dict], settings) -> str:
    available = tool_map(settings)
    tools = list(available.values())
    final_text = ""
    while True:
        response = client.chat(model=model, messages=messages, tools=tools)
        message = response.message
        assistant_message = {
            "role": "assistant",
            "content": message.content or "",
        }
        if getattr(message, "thinking", None):
            assistant_message["thinking"] = message.thinking
        if getattr(message, "tool_calls", None):
            assistant_message["tool_calls"] = [
                {
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": dict(call.function.arguments or {}),
                    },
                }
                for call in message.tool_calls
            ]
        messages.append(assistant_message)

        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            final_text = message.content or ""
            break

        for call in tool_calls:
            name = call.function.name
            arguments = dict(call.function.arguments or {})
            if name not in available:
                result = {"error": f"Unknown tool: {name}"}
            else:
                try:
                    result = available[name](**arguments)
                except Exception as exc:
                    result = {"error": str(exc), "tool": name, "arguments": arguments}
            _print_tool_event(name, arguments, result)
            messages.append(
                {
                    "role": "tool",
                    "tool_name": name,
                    "content": tool_result_content(result),
                }
            )
        final_text = message.content or final_text
    return final_text


def cmd_ask(args: argparse.Namespace) -> dict:
    settings = load_settings()
    ensure_server(settings)
    ensure_model(settings, args.model)
    client = Client(host=f"http://{settings.ollama_host}")
    messages = [
        {"role": "system", "content": _agent_system_prompt(str(settings.scope_root))},
        {"role": "user", "content": args.prompt},
    ]
    try:
        answer = _run_agent_turn(client, args.model, messages, settings)
    except ResponseError as exc:
        return {"error": exc.error, "status_code": exc.status_code}
    return {"model": args.model, "scope_root": str(settings.scope_root), "answer": answer}


def cmd_chat(args: argparse.Namespace) -> dict:
    settings = load_settings()
    ensure_server(settings)
    ensure_model(settings, args.model)
    client = Client(host=f"http://{settings.ollama_host}")
    messages = [{"role": "system", "content": _agent_system_prompt(str(settings.scope_root))}]

    print(f"Portable AI chat using {args.model}")
    print(f"Drive scope: {settings.scope_root}")
    print("Commands: /exit, /reset, /pwd, /tools")

    while True:
        try:
            prompt = input("\nYou> ").strip()
        except EOFError:
            break
        if not prompt:
            continue
        if prompt == "/exit":
            break
        if prompt == "/reset":
            messages = [{"role": "system", "content": _agent_system_prompt(str(settings.scope_root))}]
            print("Conversation reset.")
            continue
        if prompt == "/pwd":
            print(settings.scope_root)
            continue
        if prompt == "/tools":
            print(", ".join(sorted(tool_map(settings).keys())))
            continue

        messages.append({"role": "user", "content": prompt})
        try:
            answer = _run_agent_turn(client, args.model, messages, settings)
        except ResponseError as exc:
            print(f"Error: {exc.error} (status {exc.status_code})")
            continue
        print(f"\nAssistant> {answer}")

    return None


def cmd_maint_refresh(args: argparse.Namespace) -> dict:
    settings = load_settings()
    ensure_server(settings)
    ensure_model(settings, settings.embed_model)
    target = resolve_in_scope(settings, args.path)

    def progress(update: dict) -> None:
        current = update["current"]
        total = update["total"]
        path = update["path"]
        status = update["status"]
        print(
            f"[refresh] {current}/{total} {status:<9} "
            f"updated={update['updated']} unchanged={update['unchanged']} "
            f"duplicates={update['duplicates']} errors={update['errors']} :: {path}"
        )

    print(f"Refreshing library index under: {target}")
    print("This is resumable: already indexed unchanged files will be skipped on the next run.")
    result = refresh_library(settings, target, args.limit, progress_callback=progress)
    print(
        "Refresh complete. Re-running this command resumes from the current catalog and "
        "skips unchanged files."
    )
    return result


def cmd_maint_stats(args: argparse.Namespace) -> dict:
    settings = load_settings()
    return catalog_stats(settings)


def cmd_maint_duplicates(args: argparse.Namespace) -> dict:
    settings = load_settings()
    return {"duplicates": duplicate_sources(settings, args.limit)}


def cmd_maint_sample(args: argparse.Namespace) -> dict:
    settings = load_settings()
    return {
        "files": catalog_sample(
            settings,
            limit=args.limit,
            category=args.category,
            genre=args.genre,
            tag=args.tag,
            path_contains=args.path_contains,
            filename_contains=args.filename_contains,
        )
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Portable Ollama agent for the external drive.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Inspect portable tool and Ollama runtime status.")
    doctor.add_argument("--check-server", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    ask = subparsers.add_parser("ask", help="Run one agentic prompt with tool calling.")
    ask.add_argument("prompt")
    ask.add_argument("--model", default=load_settings().model_name)
    ask.set_defaults(func=cmd_ask)

    chat = subparsers.add_parser("chat", help="Interactive agentic chat with tool calling.")
    chat.add_argument("--model", default=load_settings().model_name)
    chat.set_defaults(func=cmd_chat)

    maint = subparsers.add_parser("maint", help="Library maintenance commands.")
    maint_subparsers = maint.add_subparsers(dest="maint_command", required=True)

    maint_refresh = maint_subparsers.add_parser("refresh", help="Refresh the catalog and semantic index.")
    maint_refresh.add_argument("path", nargs="?", default=".")
    maint_refresh.add_argument("--limit", type=int)
    maint_refresh.set_defaults(func=cmd_maint_refresh)

    maint_stats = maint_subparsers.add_parser("stats", help="Show catalog statistics.")
    maint_stats.set_defaults(func=cmd_maint_stats)

    maint_duplicates = maint_subparsers.add_parser("duplicates", help="Show duplicate sources.")
    maint_duplicates.add_argument("--limit", type=int, default=50)
    maint_duplicates.set_defaults(func=cmd_maint_duplicates)

    maint_sample = maint_subparsers.add_parser("sample", help="Show sample catalog rows with optional filters.")
    maint_sample.add_argument("--limit", type=int, default=50)
    maint_sample.add_argument("--category")
    maint_sample.add_argument("--genre")
    maint_sample.add_argument("--tag")
    maint_sample.add_argument("--path-contains")
    maint_sample.add_argument("--filename-contains")
    maint_sample.set_defaults(func=cmd_maint_sample)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = args.func(args)
    if result is not None:
        print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
