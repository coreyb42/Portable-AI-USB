from __future__ import annotations

from pathlib import Path

from .config import Settings


def resolve_in_scope(settings: Settings, raw: str = ".") -> Path:
    path = Path(raw).expanduser()
    candidate = path if path.is_absolute() else (settings.scope_root / path)
    resolved = candidate.resolve()
    if resolved == settings.scope_root or resolved.is_relative_to(settings.scope_root):
        return resolved
    raise ValueError(f"Path is outside the portable drive scope: {resolved}")


def display_path(settings: Settings, path: Path) -> str:
    if path == settings.scope_root:
        return "."
    return str(path.relative_to(settings.scope_root))
