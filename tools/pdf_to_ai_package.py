#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.generic import Destination

try:
    import fitz  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    fitz = None


TEXT_PREVIEW_LIMIT = 400


@dataclass(frozen=True)
class OutlineEntry:
    level: int
    title: str
    page_index: int | None


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "section"


def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def get_page_number(reader: PdfReader, dest: Destination) -> int | None:
    try:
        return int(reader.get_destination_page_number(dest)) + 1
    except Exception:
        return None


def flatten_outline(reader: PdfReader, items: list[Any], level: int = 1) -> list[OutlineEntry]:
    entries: list[OutlineEntry] = []
    for item in items:
        if isinstance(item, list):
            entries.extend(flatten_outline(reader, item, level + 1))
            continue
        title = getattr(item, "title", str(item)).strip()
        page_number = get_page_number(reader, item) if isinstance(item, Destination) else None
        entries.append(OutlineEntry(level=level, title=title, page_index=page_number))
    return entries


def choose_image_suffix(image_name: str) -> str:
    suffix = Path(image_name).suffix.lower()
    if suffix:
        return suffix
    return ".bin"


def extract_page_images(page: Any, output_dir: Path, page_number: int) -> list[dict[str, Any]]:
    images_meta: list[dict[str, Any]] = []
    for image_idx, image in enumerate(page.images, start=1):
        suffix = choose_image_suffix(image.name)
        rel_path = Path("assets") / "images" / f"page-{page_number:04d}-img-{image_idx:02d}{suffix}"
        abs_path = output_dir / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(image.data)
        images_meta.append(
            {
                "index": image_idx,
                "name": image.name,
                "path": str(rel_path).replace("\\", "/"),
                "bytes": len(image.data),
            }
        )
    return images_meta


def render_page_snapshot(
    render_doc: Any | None,
    output_dir: Path,
    page_number: int,
    render_dpi: int,
) -> str | None:
    if render_doc is None:
        return None
    rel_path = Path("assets") / "page_renders" / f"page-{page_number:04d}.png"
    abs_path = output_dir / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    page = render_doc.load_page(page_number - 1)
    scale = render_dpi / 72.0
    matrix = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    pix.save(abs_path)
    return str(rel_path).replace("\\", "/")


def build_markdown(
    source_pdf: Path,
    page_records: list[dict[str, Any]],
    outline_entries: list[OutlineEntry],
) -> str:
    lines: list[str] = []
    lines.append(f"# {source_pdf.stem}")
    lines.append("")
    lines.append("## Source")
    lines.append("")
    lines.append(f"- PDF: `{source_pdf.name}`")
    lines.append(f"- Pages: `{len(page_records)}`")
    lines.append(f"- Extracted outline entries: `{len(outline_entries)}`")
    lines.append("")
    lines.append("## Outline")
    lines.append("")
    for entry in outline_entries:
        indent = "  " * max(entry.level - 1, 0)
        page_note = f" (pdf page {entry.page_index})" if entry.page_index is not None else ""
        lines.append(f"{indent}- {entry.title}{page_note}")
    lines.append("")
    lines.append("## Pages")
    lines.append("")
    for page in page_records:
        lines.append(f"### PDF Page {page['page_number']}")
        lines.append("")
        lines.append(f"- Text chars: `{page['text_length']}`")
        lines.append(f"- Images: `{len(page['images'])}`")
        if page["page_render_path"] is not None:
            lines.append(f"- Page render: `{page['page_render_path']}`")
        if page["matched_outline_titles"]:
            lines.append("- Outline hits: " + ", ".join(f"`{title}`" for title in page["matched_outline_titles"]))
        lines.append("")
        if page["images"]:
            lines.append("#### Images")
            lines.append("")
            for image in page["images"]:
                lines.append(f"- `{image['path']}` ({image['bytes']} bytes)")
            lines.append("")
        lines.append("#### Text")
        lines.append("")
        lines.append("```text")
        lines.append(page["text"])
        lines.append("```")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def match_outline_titles(page_text: str, outline_entries: list[OutlineEntry]) -> list[str]:
    hits: list[str] = []
    for entry in outline_entries:
        if entry.title and entry.title in page_text:
            hits.append(entry.title)
    return hits[:10]


def package_pdf(source_pdf: Path, output_dir: Path) -> dict[str, Any]:
    reader = PdfReader(str(source_pdf))
    output_dir.mkdir(parents=True, exist_ok=True)
    render_doc = fitz.open(source_pdf) if fitz is not None else None

    try:
        raw_outline = reader.outline
    except Exception:
        raw_outline = []

    outline_entries = flatten_outline(reader, raw_outline if isinstance(raw_outline, list) else [])
    outline_json = [
        {
            "level": entry.level,
            "title": entry.title,
            "page_number": entry.page_index,
            "slug": slugify(entry.title),
        }
        for entry in outline_entries
    ]

    page_records: list[dict[str, Any]] = []
    for page_idx, page in enumerate(reader.pages, start=1):
        raw_text = page.extract_text() or ""
        text = normalize_text(raw_text)
        images_meta = extract_page_images(page, output_dir, page_idx)
        page_render_path = render_page_snapshot(render_doc, output_dir, page_idx, render_dpi=110)
        matched_outline_titles = match_outline_titles(text, outline_entries)
        page_records.append(
            {
                "page_number": page_idx,
                "text": text,
                "text_length": len(text),
                "text_preview": text[:TEXT_PREVIEW_LIMIT],
                "images": images_meta,
                "page_render_path": page_render_path,
                "matched_outline_titles": matched_outline_titles,
            }
        )

    markdown = build_markdown(source_pdf, page_records, outline_entries)
    (output_dir / "book.md").write_text(markdown, encoding="utf-8")
    (output_dir / "outline.json").write_text(json.dumps(outline_json, ensure_ascii=False, indent=2), encoding="utf-8")

    with (output_dir / "pages.jsonl").open("w", encoding="utf-8") as f:
        for page in page_records:
            f.write(json.dumps(page, ensure_ascii=False) + "\n")

    manifest = {
        "source_pdf": source_pdf.name,
        "source_pdf_path": str(source_pdf.resolve()),
        "num_pages": len(page_records),
        "num_outline_entries": len(outline_entries),
        "pages_with_text": sum(1 for page in page_records if page["text"]),
        "pages_with_images": sum(1 for page in page_records if page["images"]),
        "total_extracted_images": sum(len(page["images"]) for page in page_records),
        "page_renders_generated": sum(1 for page in page_records if page["page_render_path"] is not None),
        "artifacts": {
            "markdown": "book.md",
            "pages_jsonl": "pages.jsonl",
            "outline_json": "outline.json",
            "images_dir": "assets/images",
            "page_renders_dir": "assets/page_renders",
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert a PDF into an AI-friendly package.")
    parser.add_argument("source_pdf", type=Path)
    parser.add_argument("output_dir", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = package_pdf(args.source_pdf, args.output_dir)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
