from __future__ import annotations

import html
import mimetypes
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree


TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini",
    ".cfg", ".conf", ".csv", ".tsv", ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".htm",
    ".css", ".scss", ".xml", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".command", ".log",
}


@dataclass
class ReadResult:
    path: str
    file_type: str
    text: str
    sections: list[dict]
    metadata: dict


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return html.unescape(" ".join(self.parts))


def _strip_html_markup(raw: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(raw)
    return re.sub(r"\s+", " ", parser.text()).strip()


def _is_probably_text(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    mime, _ = mimetypes.guess_type(path.name)
    return bool(mime and (mime.startswith("text/") or mime in {"application/json", "application/xml"}))


def read_text_file(path: Path) -> ReadResult:
    text = path.read_text(encoding="utf-8", errors="replace")
    return ReadResult(
        path=str(path),
        file_type="text",
        text=text,
        sections=[],
        metadata={"size": path.stat().st_size},
    )


def read_pdf_file(path: Path) -> ReadResult:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    sections: list[dict] = []
    texts: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        page_text = page_text.strip()
        texts.append(page_text)
        sections.append({"page": index, "text": page_text})
    return ReadResult(
        path=str(path),
        file_type="pdf",
        text="\n\n".join(texts).strip(),
        sections=sections,
        metadata={"pages": len(reader.pages), "size": path.stat().st_size},
    )


def read_epub_file(path: Path) -> ReadResult:
    with zipfile.ZipFile(path) as archive:
        container_root = ElementTree.fromstring(archive.read("META-INF/container.xml"))
        rootfile = container_root.find(".//{*}rootfile")
        if rootfile is None:
            raise ValueError(f"EPUB container did not contain a rootfile: {path}")
        opf_path = rootfile.attrib["full-path"]
        opf_root = ElementTree.fromstring(archive.read(opf_path))
        ns = {"opf": opf_root.tag.split("}")[0].strip("{")}
        manifest = {}
        for item in opf_root.findall(".//opf:manifest/opf:item", ns):
            manifest[item.attrib["id"]] = item.attrib.get("href", "")
        spine_ids = [item.attrib["idref"] for item in opf_root.findall(".//opf:spine/opf:itemref", ns)]
        base_dir = Path(opf_path).parent
        sections: list[dict] = []
        texts: list[str] = []
        for order, item_id in enumerate(spine_ids, start=1):
            href = manifest.get(item_id)
            if not href:
                continue
            raw = archive.read(str(base_dir / href)).decode("utf-8", errors="replace")
            text = _strip_html_markup(raw)
            if not text:
                continue
            texts.append(text)
            sections.append({"section": order, "href": href, "text": text})
    return ReadResult(
        path=str(path),
        file_type="epub",
        text="\n\n".join(texts).strip(),
        sections=sections,
        metadata={"sections": len(sections), "size": path.stat().st_size},
    )


def read_path(path: Path) -> ReadResult:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf_file(path)
    if suffix == ".epub":
        return read_epub_file(path)
    if _is_probably_text(path):
        return read_text_file(path)
    raise ValueError(f"Unsupported file type for reading: {path}")


def supported_for_reading(path: Path) -> bool:
    return path.suffix.lower() in {".pdf", ".epub"} or _is_probably_text(path)
