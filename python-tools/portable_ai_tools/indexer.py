from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .ollama_runtime import embed_text
from .readers import FileTooLargeError, ReadResult, read_path, supported_for_reading


CHUNK_SIZE = 1400
CHUNK_OVERLAP = 250
SKIP_DIR_NAMES = {".git", ".venv", ".portable_tools", "ollama", "home", "logs", "__pycache__"}
CATEGORY_KEYWORDS = {
    "medical": {"medical", "medicine", "med", "health", "anatomy", "clinical", "pharmacology"},
    "survival": {"survival", "bushcraft", "prepper", "wilderness", "foraging", "homestead", "homesteading"},
    "fiction": {"fiction", "novel", "stories", "story", "fantasy", "sci-fi", "scifi", "mystery", "romance"},
    "reference": {"reference", "dictionary", "encyclopedia", "manual", "handbook", "wiktionary", "wiki"},
    "history": {"history", "historical", "war", "civilization"},
    "science": {"science", "physics", "chemistry", "biology", "math", "mathematics"},
    "technology": {"technology", "programming", "software", "computer", "computing", "ai", "machine-learning"},
}
GENRE_KEYWORDS = {
    "fantasy": {"fantasy", "sword", "magic"},
    "science_fiction": {"sci-fi", "scifi", "science fiction", "space opera", "cyberpunk"},
    "mystery": {"mystery", "detective", "crime"},
    "romance": {"romance", "love story"},
    "horror": {"horror", "ghost", "haunted"},
    "literary_fiction": {"literary", "classic"},
}


@dataclass
class ChunkMatch:
    path: str
    score: float
    chunk_index: int
    text: str
    metadata: dict


def connect_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS library_files (
            path TEXT PRIMARY KEY,
            filename TEXT,
            top_dir TEXT,
            mtime_ns INTEGER NOT NULL,
            size INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            duplicate_of TEXT,
            file_type TEXT NOT NULL,
            title TEXT,
            category TEXT,
            genre TEXT,
            tags_json TEXT NOT NULL DEFAULT '[]',
            text_chars INTEGER NOT NULL,
            page_count INTEGER,
            section_count INTEGER,
            metadata_json TEXT NOT NULL,
            indexed_at REAL NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS library_chunks (
            path TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            embedding_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            PRIMARY KEY (path, chunk_index),
            FOREIGN KEY (path) REFERENCES library_files(path) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS source_hashes (
            content_hash TEXT PRIMARY KEY,
            canonical_path TEXT NOT NULL
        )
        """
    )
    _ensure_columns(
        connection,
        "library_files",
        {
            "filename": "TEXT",
            "top_dir": "TEXT",
            "category": "TEXT",
            "genre": "TEXT",
            "tags_json": "TEXT NOT NULL DEFAULT '[]'",
        },
    )
    return connection


def _ensure_columns(connection: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for column, ddl in columns.items():
        if column not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


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


def _classify_metadata(display_path: str, title: str) -> dict:
    path_obj = Path(display_path)
    path_parts = [part.lower() for part in path_obj.parts]
    haystack = " ".join(path_parts + [title.lower(), path_obj.stem.lower()])

    top_dir = path_parts[0] if path_parts else ""
    category = None
    for candidate, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            category = candidate
            break
    if category is None and top_dir:
        category = top_dir.replace("-", "_")

    genre = None
    for candidate, keywords in GENRE_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            genre = candidate
            break

    tags = sorted({part.replace(" ", "_") for part in path_parts[:5] if part and not part.startswith(".")})
    if category:
        tags.append(category)
    if genre:
        tags.append(genre)
    return {
        "filename": path_obj.name,
        "top_dir": top_dir or None,
        "category": category,
        "genre": genre,
        "tags": sorted(set(tags)),
    }


def _matches_filters(metadata: dict, filters: dict | None) -> bool:
    if not filters:
        return True
    category = filters.get("category")
    if category and str(metadata.get("category", "")).lower() != str(category).lower():
        return False
    genre = filters.get("genre")
    if genre and str(metadata.get("genre", "")).lower() != str(genre).lower():
        return False
    path_contains = filters.get("path_contains")
    if path_contains and str(path_contains).lower() not in str(metadata.get("path", "")).lower():
        return False
    filename_contains = filters.get("filename_contains")
    if filename_contains and str(filename_contains).lower() not in str(metadata.get("filename", "")).lower():
        return False
    tag = filters.get("tag")
    if tag and str(tag).lower() not in {str(item).lower() for item in metadata.get("tags", [])}:
        return False
    return True


def _chunk_text(text: str) -> list[tuple[int, int, str]]:
    clean = " ".join(text.split())
    if not clean:
        return []
    chunks: list[tuple[int, int, str]] = []
    start = 0
    while start < len(clean):
        end = min(start + CHUNK_SIZE, len(clean))
        chunk = clean[start:end].strip()
        if chunk:
            chunks.append((start, end, chunk))
        if end >= len(clean):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def _chunk_sections(content: ReadResult) -> list[dict]:
    if content.sections:
        chunks: list[dict] = []
        for section_index, section in enumerate(content.sections):
            section_text = section.get("text", "")
            if not section_text.strip():
                continue
            for local_index, (start, end, chunk_text) in enumerate(_chunk_text(section_text)):
                metadata = {key: value for key, value in section.items() if key != "text"}
                metadata["section_index"] = section_index
                metadata["section_chunk_index"] = local_index
                metadata["section_start_char"] = start
                metadata["section_end_char"] = end
                chunks.append({"text": chunk_text, "metadata": metadata})
        if chunks:
            return chunks
    return [{"text": chunk, "metadata": {"section_index": 0}} for _, _, chunk in _chunk_text(content.text)]


def _title_from_content(path: Path, content: ReadResult) -> str:
    if content.metadata.get("title"):
        return str(content.metadata["title"])
    if content.sections:
        for section in content.sections[:3]:
            text = section.get("text", "").strip()
            if text:
                first_line = text.splitlines()[0].strip()
                if first_line:
                    return first_line[:160]
    return path.stem


def _file_record(path: Path, display_path: str, content: ReadResult, content_hash: str) -> dict:
    metadata = dict(content.metadata)
    title = _title_from_content(path, content)
    derived = _classify_metadata(display_path, title)
    return {
        "path": display_path,
        "filename": derived["filename"],
        "top_dir": derived["top_dir"],
        "content_hash": content_hash,
        "duplicate_of": None,
        "file_type": content.file_type,
        "title": title,
        "category": derived["category"],
        "genre": derived["genre"],
        "tags_json": json.dumps(derived["tags"]),
        "text_chars": len(content.text),
        "page_count": metadata.get("pages"),
        "section_count": len(content.sections),
        "metadata_json": json.dumps({**metadata, **derived}),
        "indexed_at": time.time(),
    }

def refresh_library(
    settings: Settings,
    target: Path,
    limit: int | None = None,
    progress_callback=None,
) -> dict:
    connection = connect_db(settings.index_db)
    processed = 0
    updated = 0
    unchanged = 0
    duplicates = 0
    errors = 0
    skipped_large = 0
    paths = _walk_files(target)
    total = len(paths)
    if limit is not None:
        paths = paths[:limit]
        total = len(paths)

    for path in paths:
        processed += 1
        display_path = _relative_display(settings.scope_root, path)
        stat = path.stat()
        try:
            content = read_path(path, max_file_bytes=settings.max_read_file_mb * 1024 * 1024)
        except FileTooLargeError:
            skipped_large += 1
            if progress_callback:
                progress_callback(
                    {
                        "current": processed,
                        "total": total,
                        "path": display_path,
                        "status": "skipped_large",
                        "updated": updated,
                        "unchanged": unchanged,
                        "duplicates": duplicates,
                        "errors": errors,
                        "skipped_large": skipped_large,
                    }
                )
            continue
        except Exception:
            errors += 1
            if progress_callback:
                progress_callback(
                    {
                        "current": processed,
                        "total": total,
                        "path": display_path,
                        "status": "error",
                        "updated": updated,
                        "unchanged": unchanged,
                        "duplicates": duplicates,
                        "errors": errors,
                        "skipped_large": skipped_large,
                    }
                )
            continue

        content_hash = _content_hash(content.text)
        existing = connection.execute(
            "SELECT mtime_ns, size, content_hash, duplicate_of FROM library_files WHERE path = ?",
            (display_path,),
        ).fetchone()
        if (
            existing
            and existing["mtime_ns"] == stat.st_mtime_ns
            and existing["size"] == stat.st_size
            and existing["content_hash"] == content_hash
        ):
            unchanged += 1
            if progress_callback:
                progress_callback(
                    {
                        "current": processed,
                        "total": total,
                        "path": display_path,
                        "status": "unchanged",
                        "updated": updated,
                        "unchanged": unchanged,
                        "duplicates": duplicates,
                        "errors": errors,
                        "skipped_large": skipped_large,
                    }
                )
            continue

        record = _file_record(path, display_path, content, content_hash)
        canonical = connection.execute(
            "SELECT canonical_path FROM source_hashes WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        duplicate_of = None
        if canonical and canonical["canonical_path"] != display_path:
            duplicate_of = canonical["canonical_path"]
            duplicates += 1

        with connection:
            connection.execute("DELETE FROM library_chunks WHERE path = ?", (display_path,))
            connection.execute(
                """
                INSERT INTO library_files(
                    path, filename, top_dir, mtime_ns, size, content_hash, duplicate_of, file_type, title,
                    category, genre, tags_json, text_chars, page_count, section_count, metadata_json, indexed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    filename = excluded.filename,
                    top_dir = excluded.top_dir,
                    mtime_ns = excluded.mtime_ns,
                    size = excluded.size,
                    content_hash = excluded.content_hash,
                    duplicate_of = excluded.duplicate_of,
                    file_type = excluded.file_type,
                    title = excluded.title,
                    category = excluded.category,
                    genre = excluded.genre,
                    tags_json = excluded.tags_json,
                    text_chars = excluded.text_chars,
                    page_count = excluded.page_count,
                    section_count = excluded.section_count,
                    metadata_json = excluded.metadata_json,
                    indexed_at = excluded.indexed_at
                """,
                (
                    display_path,
                    record["filename"],
                    record["top_dir"],
                    stat.st_mtime_ns,
                    stat.st_size,
                    content_hash,
                    duplicate_of,
                    record["file_type"],
                    record["title"],
                    record["category"],
                    record["genre"],
                    record["tags_json"],
                    record["text_chars"],
                    record["page_count"],
                    record["section_count"],
                    record["metadata_json"],
                    record["indexed_at"],
                ),
            )

            if duplicate_of is None:
                connection.execute(
                    """
                    INSERT INTO source_hashes(content_hash, canonical_path)
                    VALUES (?, ?)
                    ON CONFLICT(content_hash) DO UPDATE SET canonical_path = excluded.canonical_path
                    """,
                    (content_hash, display_path),
                )
                chunk_rows = []
                for chunk_index, chunk in enumerate(_chunk_sections(content)):
                    chunk_rows.append(
                        (
                            display_path,
                            chunk_index,
                            chunk["text"],
                            json.dumps(embed_text(settings, chunk["text"])),
                            json.dumps(
                                {
                                    "file_type": content.file_type,
                                    "path": display_path,
                                    "filename": record["filename"],
                                    "top_dir": record["top_dir"],
                                    "title": record["title"],
                                    "category": record["category"],
                                    "genre": record["genre"],
                                    "tags": json.loads(record["tags_json"]),
                                    **content.metadata,
                                    **chunk["metadata"],
                                }
                            ),
                        )
                    )
                if chunk_rows:
                    connection.executemany(
                        """
                        INSERT OR REPLACE INTO library_chunks(path, chunk_index, text, embedding_json, metadata_json)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        chunk_rows,
                    )
        updated += 1
        if progress_callback:
            progress_callback(
                {
                    "current": processed,
                    "total": total,
                    "path": display_path,
                    "status": "duplicate" if duplicate_of else "updated",
                    "updated": updated,
                    "unchanged": unchanged,
                    "duplicates": duplicates,
                    "errors": errors,
                    "skipped_large": skipped_large,
                }
            )

    return {
        "processed_files": processed,
        "total_files": total,
        "updated_files": updated,
        "unchanged_files": unchanged,
        "duplicate_files": duplicates,
        "error_files": errors,
        "skipped_large_files": skipped_large,
        "database": str(settings.index_db),
    }


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def semantic_search(
    settings: Settings,
    query: str,
    limit: int = 5,
    path_prefix: str | None = None,
    filters: dict | None = None,
) -> list[ChunkMatch]:
    connection = connect_db(settings.index_db)
    query_embedding = embed_text(settings, query)
    if path_prefix:
        rows = connection.execute(
            """
            SELECT c.path, c.chunk_index, c.text, c.embedding_json, c.metadata_json
            FROM library_chunks c
            JOIN library_files f ON f.path = c.path
            WHERE f.duplicate_of IS NULL AND c.path LIKE ?
            """,
            (f"{path_prefix}%",),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT c.path, c.chunk_index, c.text, c.embedding_json, c.metadata_json
            FROM library_chunks c
            JOIN library_files f ON f.path = c.path
            WHERE f.duplicate_of IS NULL
            """
        ).fetchall()
    matches: list[ChunkMatch] = []
    for row in rows:
        metadata = json.loads(row["metadata_json"])
        if not _matches_filters(metadata, filters):
            continue
        score = _cosine_similarity(query_embedding, json.loads(row["embedding_json"]))
        matches.append(
            ChunkMatch(
                path=row["path"],
                score=score,
                chunk_index=row["chunk_index"],
                text=row["text"],
                metadata=metadata,
            )
        )
    matches.sort(key=lambda item: item.score, reverse=True)
    return matches[:limit]


def _char_to_line(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def locate_exact_phrase(
    settings: Settings,
    phrase: str,
    root_dir: Path,
    limit: int = 10,
    filters: dict | None = None,
) -> list[dict]:
    phrase_lower = phrase.lower()
    results: list[dict] = []
    for path in _walk_files(root_dir):
        try:
            content = read_path(path, max_file_bytes=settings.max_read_file_mb * 1024 * 1024)
        except FileTooLargeError:
            continue
        except Exception:
            continue
        display_path = _relative_display(settings.scope_root, path)
        derived = _classify_metadata(display_path, _title_from_content(path, content))
        base_metadata = {
            "path": display_path,
            "filename": derived["filename"],
            "top_dir": derived["top_dir"],
            "category": derived["category"],
            "genre": derived["genre"],
            "tags": derived["tags"],
        }
        if not _matches_filters(base_metadata, filters):
            continue

        if content.sections:
            for section in content.sections:
                section_text = section.get("text", "")
                idx = section_text.lower().find(phrase_lower)
                if idx < 0:
                    continue
                entry = {
                    "path": display_path,
                    "file_type": content.file_type,
                    "metadata": base_metadata,
                    "quote": section_text[idx : idx + len(phrase)],
                    "snippet": section_text[max(0, idx - 140) : idx + len(phrase) + 140].replace("\n", " ").strip(),
                    "location": {key: value for key, value in section.items() if key != "text"},
                }
                results.append(entry)
                if len(results) >= limit:
                    return results
        else:
            idx = content.text.lower().find(phrase_lower)
            if idx < 0:
                continue
            line = _char_to_line(content.text, idx)
            results.append(
                {
                    "path": display_path,
                    "file_type": content.file_type,
                    "metadata": base_metadata,
                    "quote": content.text[idx : idx + len(phrase)],
                    "snippet": content.text[max(0, idx - 140) : idx + len(phrase) + 140].replace("\n", " ").strip(),
                    "location": {"line": line},
                }
            )
            if len(results) >= limit:
                return results
    return results


def plain_text_search(root_dir: Path, query: str, limit: int = 20, filters: dict | None = None) -> list[dict]:
    query_lower = query.lower()
    results: list[dict] = []
    for path in _walk_files(root_dir):
        if len(results) >= limit:
            break
        rel_path = _relative_display(root_dir, path)
        derived = _classify_metadata(rel_path, path.stem)
        base_metadata = {
            "path": rel_path,
            "filename": derived["filename"],
            "top_dir": derived["top_dir"],
            "category": derived["category"],
            "genre": derived["genre"],
            "tags": derived["tags"],
        }
        if not _matches_filters(base_metadata, filters):
            continue
        if query_lower in rel_path.lower():
            results.append({"path": rel_path, "match_type": "path", "metadata": base_metadata})
            continue
        try:
            content = read_path(path, max_file_bytes=settings.max_read_file_mb * 1024 * 1024)
        except Exception:
            continue
        content_lower = content.text.lower()
        if query_lower not in content_lower:
            continue
        index = content_lower.index(query_lower)
        start = max(index - 160, 0)
        end = min(index + len(query) + 160, len(content.text))
        snippet = content.text[start:end].replace("\n", " ").strip()
        location = {}
        if content.sections:
            for section in content.sections:
                section_text = section.get("text", "")
                if query_lower in section_text.lower():
                    location = {key: value for key, value in section.items() if key != "text"}
                    break
        results.append({"path": rel_path, "match_type": "content", "snippet": snippet, "location": location, "metadata": base_metadata})
    return results


def catalog_stats(settings: Settings) -> dict:
    connection = connect_db(settings.index_db)
    totals = connection.execute(
        """
        SELECT
            COUNT(*) AS file_count,
            SUM(CASE WHEN duplicate_of IS NOT NULL THEN 1 ELSE 0 END) AS duplicate_count,
            SUM(CASE WHEN duplicate_of IS NULL THEN 1 ELSE 0 END) AS canonical_count,
            COALESCE(SUM(text_chars), 0) AS text_chars
        FROM library_files
        """
    ).fetchone()
    by_type_rows = connection.execute(
        """
        SELECT file_type, COUNT(*) AS count
        FROM library_files
        GROUP BY file_type
        ORDER BY count DESC, file_type
        """
    ).fetchall()
    by_category_rows = connection.execute(
        """
        SELECT category, COUNT(*) AS count
        FROM library_files
        GROUP BY category
        ORDER BY count DESC, category
        """
    ).fetchall()
    return {
        "file_count": totals["file_count"] or 0,
        "canonical_count": totals["canonical_count"] or 0,
        "duplicate_count": totals["duplicate_count"] or 0,
        "text_chars": totals["text_chars"] or 0,
        "by_type": [{row["file_type"]: row["count"]} for row in by_type_rows],
        "by_category": [{str(row["category"]): row["count"]} for row in by_category_rows],
    }


def duplicate_sources(settings: Settings, limit: int = 50) -> list[dict]:
    connection = connect_db(settings.index_db)
    rows = connection.execute(
        """
        SELECT path, duplicate_of, title, file_type
        FROM library_files
        WHERE duplicate_of IS NOT NULL
        ORDER BY duplicate_of, path
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "path": row["path"],
            "duplicate_of": row["duplicate_of"],
            "title": row["title"],
            "file_type": row["file_type"],
        }
        for row in rows
    ]


def catalog_sample(
    settings: Settings,
    limit: int = 50,
    category: str | None = None,
    genre: str | None = None,
    tag: str | None = None,
    path_contains: str | None = None,
    filename_contains: str | None = None,
) -> list[dict]:
    connection = connect_db(settings.index_db)
    rows = connection.execute(
        """
        SELECT path, filename, top_dir, title, file_type, category, genre, tags_json, duplicate_of
        FROM library_files
        ORDER BY path
        """
    ).fetchall()
    filters = {
        key: value
        for key, value in {
            "category": category,
            "genre": genre,
            "tag": tag,
            "path_contains": path_contains,
            "filename_contains": filename_contains,
        }.items()
        if value
    }
    results = []
    for row in rows:
        metadata = {
            "path": row["path"],
            "filename": row["filename"],
            "top_dir": row["top_dir"],
            "category": row["category"],
            "genre": row["genre"],
            "tags": json.loads(row["tags_json"] or "[]"),
        }
        if not _matches_filters(metadata, filters):
            continue
        results.append(
            {
                "path": row["path"],
                "filename": row["filename"],
                "top_dir": row["top_dir"],
                "title": row["title"],
                "file_type": row["file_type"],
                "category": row["category"],
                "genre": row["genre"],
                "tags": json.loads(row["tags_json"] or "[]"),
                "duplicate_of": row["duplicate_of"],
            }
        )
        if len(results) >= limit:
            break
    return results
