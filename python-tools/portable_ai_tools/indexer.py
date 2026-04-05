from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .ollama_runtime import embed_text
from .readers import ReadResult, read_path, supported_for_reading


CHUNK_SIZE = 1400
CHUNK_OVERLAP = 250
SKIP_DIR_NAMES = {".git", ".venv", ".portable_tools", "ollama", "home", "logs", "__pycache__"}


@dataclass
class ChunkMatch:
    path: str
    score: float
    chunk_index: int
    text: str
    metadata: dict


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            mtime_ns INTEGER NOT NULL,
            size INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            path TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            embedding_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            PRIMARY KEY (path, chunk_index),
            FOREIGN KEY (path) REFERENCES files(path) ON DELETE CASCADE
        )
        """
    )
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _chunk_text(text: str) -> list[str]:
    clean = " ".join(text.split())
    if not clean:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(start + CHUNK_SIZE, len(clean))
        chunk = clean[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(clean):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def _walk_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    paths: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIR_NAMES]
        current_dir = Path(dirpath)
        for filename in filenames:
            path = current_dir / filename
            if supported_for_reading(path):
                paths.append(path)
    return sorted(paths)


def _relative_display(root_dir: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root_dir))
    except ValueError:
        return str(path)


def index_paths(settings: Settings, target: Path, limit: int | None = None) -> dict:
    connection = _connect(settings.index_db)
    indexed = 0
    skipped = 0
    for path in _walk_files(target):
        if limit is not None and indexed >= limit:
            break
        stat = path.stat()
        display_path = _relative_display(settings.root_dir, path)
        try:
            content = read_path(path)
        except Exception:
            skipped += 1
            continue
        content_hash = _content_hash(content.text)
        row = connection.execute(
            "SELECT mtime_ns, size, content_hash FROM files WHERE path = ?",
            (display_path,),
        ).fetchone()
        if row and row[0] == stat.st_mtime_ns and row[1] == stat.st_size and row[2] == content_hash:
            skipped += 1
            continue

        chunks = _chunk_text(content.text)
        embeddings = [embed_text(settings, chunk) for chunk in chunks]
        with connection:
            connection.execute("DELETE FROM chunks WHERE path = ?", (display_path,))
            connection.execute(
                """
                INSERT INTO files(path, mtime_ns, size, content_hash, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    mtime_ns = excluded.mtime_ns,
                    size = excluded.size,
                    content_hash = excluded.content_hash,
                    metadata_json = excluded.metadata_json
                """,
                (
                    display_path,
                    stat.st_mtime_ns,
                    stat.st_size,
                    content_hash,
                    json.dumps(content.metadata),
                ),
            )
            connection.executemany(
                """
                INSERT OR REPLACE INTO chunks(path, chunk_index, text, embedding_json, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        display_path,
                        index,
                        chunk,
                        json.dumps(embedding),
                        json.dumps({"file_type": content.file_type, **content.metadata}),
                    )
                    for index, (chunk, embedding) in enumerate(zip(chunks, embeddings))
                ],
            )
        indexed += 1
    return {"indexed_files": indexed, "skipped_files": skipped, "database": str(settings.index_db)}


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def semantic_search(settings: Settings, query: str, limit: int = 5) -> list[ChunkMatch]:
    connection = _connect(settings.index_db)
    query_embedding = embed_text(settings, query)
    rows = connection.execute(
        "SELECT path, chunk_index, text, embedding_json, metadata_json FROM chunks"
    ).fetchall()
    matches: list[ChunkMatch] = []
    for path, chunk_index, text, embedding_json, metadata_json in rows:
        score = _cosine_similarity(query_embedding, json.loads(embedding_json))
        matches.append(
            ChunkMatch(
                path=path,
                score=score,
                chunk_index=chunk_index,
                text=text,
                metadata=json.loads(metadata_json),
            )
        )
    matches.sort(key=lambda item: item.score, reverse=True)
    return matches[:limit]


def plain_text_search(root_dir: Path, query: str, limit: int = 20) -> list[dict]:
    query_lower = query.lower()
    results: list[dict] = []
    for path in _walk_files(root_dir):
        if len(results) >= limit:
            break
        rel_path = _relative_display(root_dir, path)
        if query_lower in rel_path.lower():
            results.append({"path": rel_path, "match_type": "path"})
            continue
        try:
            content: ReadResult = read_path(path)
        except Exception:
            continue
        content_lower = content.text.lower()
        if query_lower not in content_lower:
            continue
        index = content_lower.index(query_lower)
        start = max(index - 160, 0)
        end = min(index + len(query) + 160, len(content.text))
        snippet = content.text[start:end].replace("\n", " ").strip()
        results.append({"path": rel_path, "match_type": "content", "snippet": snippet})
    return results
