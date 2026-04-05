from __future__ import annotations

import argparse
import json

from ollama import Client, ResponseError

from .agent import tool_map, tool_result_content
from .config import load_settings
from .ollama_runtime import ensure_model, ensure_server, find_ollama_binary, server_running


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

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = args.func(args)
    if result is not None:
        print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
