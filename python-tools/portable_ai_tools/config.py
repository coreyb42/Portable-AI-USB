from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _read_shell_config(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    scope_root: Path
    data_dir: Path
    index_db: Path
    logs_dir: Path
    ollama_models: Path
    model_name: str
    embed_model: str
    ollama_host: str
    max_read_file_mb: int


def load_settings() -> Settings:
    root_dir = Path(__file__).resolve().parents[2]
    conf = _read_shell_config(root_dir / "portable-ai.conf")
    data_dir = root_dir / ".portable_tools"
    return Settings(
        root_dir=root_dir,
        scope_root=(root_dir / "../..").resolve(),
        data_dir=data_dir,
        index_db=data_dir / "semantic_index.sqlite3",
        logs_dir=root_dir / "logs",
        ollama_models=root_dir / "ollama" / "models",
        model_name=conf.get("MODEL_NAME", "gemma4:e4b"),
        embed_model=conf.get("EMBED_MODEL", "nomic-embed-text"),
        ollama_host=os.environ.get("OLLAMA_HOST", conf.get("OLLAMA_HOST", "127.0.0.1:11434")),
        max_read_file_mb=int(conf.get("MAX_READ_FILE_MB", "512")),
    )
