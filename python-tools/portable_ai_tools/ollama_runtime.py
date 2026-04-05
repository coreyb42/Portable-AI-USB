from __future__ import annotations

import atexit
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .config import Settings

_SERVER_PROCESS: subprocess.Popen[bytes] | None = None


def _platform_dir(settings: Settings) -> Path:
    if os.uname().sysname == "Darwin":
        return settings.root_dir / "ollama" / "macos"
    return settings.root_dir / "ollama" / f"linux-{os.uname().machine}"


def find_ollama_binary(settings: Settings) -> Path:
    platform_dir = _platform_dir(settings)
    candidates = (
        platform_dir / "bin" / "ollama",
        platform_dir / "ollama",
        platform_dir / "Ollama.app" / "Contents" / "Resources" / "ollama",
        platform_dir / "Ollama.app" / "Contents" / "MacOS" / "Ollama",
    )
    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    raise FileNotFoundError(
        f"Portable Ollama binary not found for this platform under {platform_dir}. "
        f"Run the repo installer first."
    )


def _base_url(settings: Settings) -> str:
    return f"http://{settings.ollama_host}"


def _runtime_env(settings: Settings) -> dict[str, str]:
    env = os.environ.copy()
    platform_home = "macos" if os.uname().sysname == "Darwin" else "linux"
    env["HOME"] = str(settings.root_dir / "home" / platform_home)
    env["XDG_DATA_HOME"] = str(Path(env["HOME"]) / ".local" / "share")
    env["XDG_CONFIG_HOME"] = str(Path(env["HOME"]) / ".config")
    env["XDG_STATE_HOME"] = str(Path(env["HOME"]) / ".local" / "state")
    env["OLLAMA_MODELS"] = str(settings.ollama_models)
    env["OLLAMA_HOST"] = settings.ollama_host
    env["OLLAMA_NO_CLOUD"] = "1"
    Path(env["XDG_DATA_HOME"]).mkdir(parents=True, exist_ok=True)
    Path(env["XDG_CONFIG_HOME"]).mkdir(parents=True, exist_ok=True)
    Path(env["XDG_STATE_HOME"]).mkdir(parents=True, exist_ok=True)
    settings.ollama_models.mkdir(parents=True, exist_ok=True)
    return env


def _log_tail(path: Path, max_lines: int = 20) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])


def _request_json(settings: Settings, path: str, payload: dict | None = None, timeout: int = 30) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        urllib.parse.urljoin(_base_url(settings), path),
        data=data,
        headers=headers,
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def server_running(settings: Settings) -> bool:
    try:
        _request_json(settings, "/api/tags", timeout=3)
        return True
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return False


def ensure_server(settings: Settings) -> None:
    global _SERVER_PROCESS
    if server_running(settings):
        return
    binary = find_ollama_binary(settings)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    env = _runtime_env(settings)
    log_path = settings.logs_dir / "python-tools-ollama.log"
    with log_path.open("ab") as log_file:
        _SERVER_PROCESS = subprocess.Popen(
            [str(binary), "serve"],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=settings.root_dir,
            start_new_session=True,
        )
    atexit.register(stop_server)
    for _ in range(30):
        if server_running(settings):
            return
        if _SERVER_PROCESS is not None and _SERVER_PROCESS.poll() is not None:
            break
        time.sleep(1)
    tail = _log_tail(log_path)
    raise RuntimeError(
        "Portable Ollama server did not become ready in time.\n"
        f"Binary: {binary}\n"
        f"Log: {log_path}\n"
        f"{tail}"
    )


def stop_server() -> None:
    global _SERVER_PROCESS
    if _SERVER_PROCESS is not None and _SERVER_PROCESS.poll() is None:
        _SERVER_PROCESS.terminate()
        try:
            _SERVER_PROCESS.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _SERVER_PROCESS.kill()
    _SERVER_PROCESS = None


def ensure_model(settings: Settings, model: str) -> None:
    ensure_server(settings)
    tags = _request_json(settings, "/api/tags")
    names = {item["name"] for item in tags.get("models", [])}
    if model in names:
        return
    binary = find_ollama_binary(settings)
    subprocess.run([str(binary), "pull", model], check=True, cwd=settings.root_dir, env=_runtime_env(settings))


def embed_text(settings: Settings, text: str, model: str | None = None) -> list[float]:
    embed_model = model or settings.embed_model
    ensure_model(settings, embed_model)
    response = _request_json(
        settings,
        "/api/embeddings",
        {"model": embed_model, "prompt": text},
        timeout=120,
    )
    vector = response.get("embedding")
    if not isinstance(vector, list):
        raise RuntimeError("Ollama embeddings response did not contain an embedding vector.")
    return [float(value) for value in vector]
