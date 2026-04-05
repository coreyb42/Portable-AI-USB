from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from .config import Settings
from .fsops import display_path, resolve_in_scope
from .indexer import locate_exact_phrase, plain_text_search, refresh_library, semantic_search
from .ollama_runtime import ensure_model, ensure_server
from .readers import read_path


ToolCallable = Callable[..., dict]


@dataclass
class ToolContext:
    settings: Settings

    def _filters(
        self,
        category: str | None = None,
        genre: str | None = None,
        tag: str | None = None,
        path_contains: str | None = None,
        filename_contains: str | None = None,
    ) -> dict:
        return {
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

    def browse(
        self,
        path: str = ".",
        limit: int = 100,
        recursive: bool = False,
        max_depth: int = 2,
        include_hidden: bool = False,
    ) -> dict:
        """Browse files and directories on the external drive.

        Args:
          path: Relative path from the drive root. Defaults to the drive root.
          limit: Maximum number of entries to return.
          recursive: Whether to recurse into subdirectories.
          max_depth: Maximum recursive depth when recursive is true.
          include_hidden: Whether to include dotfiles and dot-directories.

        Returns:
          Directory entries with names, relative paths, types, and sizes.
        """
        target = resolve_in_scope(self.settings, path)
        if not target.exists():
            raise FileNotFoundError(target)
        if target.is_file():
            stat = target.stat()
            return {
                "path": display_path(self.settings, target),
                "entries": [{
                    "name": target.name,
                    "path": display_path(self.settings, target),
                    "type": "file",
                    "size": stat.st_size,
                }],
            }

        entries: list[dict] = []
        root_depth = len(target.parts)
        iterator = target.rglob("*") if recursive else target.iterdir()
        for child in sorted(iterator):
            if not include_hidden and any(part.startswith(".") for part in child.relative_to(target).parts):
                continue
            if recursive and len(child.parts) - root_depth > max_depth:
                continue
            stat = child.stat()
            entries.append(
                {
                    "name": child.name,
                    "path": display_path(self.settings, child),
                    "type": "directory" if child.is_dir() else "file",
                    "size": stat.st_size,
                }
            )
            if len(entries) >= limit:
                break
        return {"path": display_path(self.settings, target), "entries": entries}

    def search(
        self,
        query: str,
        path: str = ".",
        limit: int = 20,
        category: str | None = None,
        genre: str | None = None,
        tag: str | None = None,
        path_contains: str | None = None,
        filename_contains: str | None = None,
    ) -> dict:
        """Search file paths and text content on the external drive.

        Args:
          query: Query string to find in paths or text.
          path: Relative path from the drive root to search under.
          limit: Maximum number of matches to return.
          category: Optional high-level category filter such as medical, survival, or fiction.
          genre: Optional genre filter.
          tag: Optional tag filter derived from path metadata.
          path_contains: Optional substring filter applied to relative paths.
          filename_contains: Optional substring filter applied to filenames.

        Returns:
          Matching file paths and snippets.
        """
        target = resolve_in_scope(self.settings, path)
        filters = self._filters(category, genre, tag, path_contains, filename_contains)
        return {"query": query, "filters": filters, "results": plain_text_search(target, query, limit, filters=filters)}

    def read(
        self,
        path: str,
        max_chars: int = 12000,
        include_sections: bool = False,
        max_sections: int = 20,
    ) -> dict:
        """Read a text, PDF, or EPUB file from the external drive.

        Args:
          path: Relative path from the drive root to the file.
          max_chars: Maximum characters of combined text to return.
          include_sections: Whether to include per-page or per-section extracts.
          max_sections: Maximum number of sections to return.

        Returns:
          Extracted text and metadata for the file.
        """
        target = resolve_in_scope(self.settings, path)
        result = read_path(target, max_file_bytes=self.settings.max_read_file_mb * 1024 * 1024)
        payload = {
            "path": display_path(self.settings, target),
            "file_type": result.file_type,
            "metadata": result.metadata,
            "text": result.text[:max_chars],
        }
        if include_sections:
            payload["sections"] = result.sections[:max_sections]
        return payload

    def index(self, path: str = ".", limit: int | None = None) -> dict:
        """Build or refresh the semantic index and file catalog for supported files.

        Args:
          path: Relative path from the drive root to index.
          limit: Optional file limit for partial indexing.

        Returns:
          Indexing summary including indexed and skipped file counts.
        """
        ensure_server(self.settings)
        ensure_model(self.settings, self.settings.embed_model)
        target = resolve_in_scope(self.settings, path)
        return refresh_library(self.settings, target, limit)

    def locate_quote(
        self,
        quote: str,
        path: str = ".",
        limit: int = 10,
        category: str | None = None,
        genre: str | None = None,
        tag: str | None = None,
        path_contains: str | None = None,
        filename_contains: str | None = None,
    ) -> dict:
        """Locate an exact phrase within files and return file/location references.

        Args:
          quote: Exact phrase to find.
          path: Relative path from the drive root to search under.
          limit: Maximum number of matches to return.
          category: Optional high-level category filter such as medical, survival, or fiction.
          genre: Optional genre filter.
          tag: Optional tag filter derived from path metadata.
          path_contains: Optional substring filter applied to relative paths.
          filename_contains: Optional substring filter applied to filenames.

        Returns:
          Matching files with page, section, or line references.
        """
        target = resolve_in_scope(self.settings, path)
        filters = self._filters(category, genre, tag, path_contains, filename_contains)
        return {
            "quote": quote,
            "filters": filters,
            "results": locate_exact_phrase(self.settings, quote, target, limit, filters=filters),
        }

    def semantic_search(
        self,
        query: str,
        path: str = ".",
        limit: int = 5,
        category: str | None = None,
        genre: str | None = None,
        tag: str | None = None,
        path_contains: str | None = None,
        filename_contains: str | None = None,
    ) -> dict:
        """Search the semantic index for conceptually relevant content.

        Args:
          query: Semantic query text.
          path: Relative path from the drive root to filter the indexed corpus.
          limit: Maximum number of matches to return.
          category: Optional high-level category filter such as medical, survival, or fiction.
          genre: Optional genre filter.
          tag: Optional tag filter derived from path metadata.
          path_contains: Optional substring filter applied to relative paths.
          filename_contains: Optional substring filter applied to filenames.

        Returns:
          Ranked semantic matches from indexed content.
        """
        ensure_server(self.settings)
        ensure_model(self.settings, self.settings.embed_model)
        target = resolve_in_scope(self.settings, path)
        prefix = display_path(self.settings, target)
        if prefix == ".":
            prefix = None
        filters = self._filters(category, genre, tag, path_contains, filename_contains)
        matches = semantic_search(self.settings, query, limit, path_prefix=prefix, filters=filters)
        return {
            "query": query,
            "filters": filters,
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


def tool_map(settings: Settings) -> dict[str, ToolCallable]:
    ctx = ToolContext(settings)
    return {
        "browse": ctx.browse,
        "search": ctx.search,
        "read": ctx.read,
        "index": ctx.index,
        "locate_quote": ctx.locate_quote,
        "semantic_search": ctx.semantic_search,
    }


def tool_result_content(result: dict) -> str:
    return json.dumps(result, ensure_ascii=True, indent=2)
