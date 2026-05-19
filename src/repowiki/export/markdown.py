"""export wiki as a directory of Markdown files."""

from __future__ import annotations

import json
import hashlib
import shutil
from pathlib import Path

from repowiki.core.wiki_builder import Wiki, SidebarItem


def export_markdown(wiki: Wiki, output_dir: str | Path, generation_mode: str = "full") -> None:
    """write each wiki page as a .md file in content/ subdirectory, plus a _sidebar.md for navigation.

    generation_mode:
        "full" = full regenerate (delete all files first, then generate fresh)
        "incremental" = resume from record (only regenerate changed pages)
    """
    out = Path(output_dir)
    content_dir = out / "content"
    record_path = out / ".repowiki_generation_record.json"

    # Load generation record for incremental mode
    generation_record = {}
    if generation_mode == "incremental" and record_path.exists():
        try:
            generation_record = json.loads(record_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            generation_record = {}

    # Full mode: Clear output directory before generating
    if generation_mode == "full":
        if content_dir.exists():
            shutil.rmtree(content_dir)
        if (out / "_sidebar.md").exists():
            (out / "_sidebar.md").unlink()
        generation_record = {}

    # Ensure directories exist
    content_dir.mkdir(parents=True, exist_ok=True)

    # write each page under content/
    for page in wiki.pages:
        # Handle multi-level paths by creating proper directory structure
        # e.g., "docs/核心架构/核心组件详解/核心组件详解" creates content/docs/核心架构/核心组件详解/核心组件详解.md
        page_path = content_dir / f"{page.id}.md"
        page_path.parent.mkdir(parents=True, exist_ok=True)

        # Compute content hash
        content_hash = hashlib.md5(page.content.encode("utf-8")).hexdigest()

        # Incremental mode: Skip if content unchanged
        if generation_mode == "incremental":
            existing_record = generation_record.get(page.id)
            if existing_record and existing_record.get("hash") == content_hash:
                continue  # Skip unchanged page

        page_path.write_text(page.content, encoding="utf-8")
        generation_record[page.id] = {
            "path": str(page_path),
            "hash": content_hash,
        }

    # write sidebar navigation at root level with recursive children support
    sidebar_lines = [f"# {wiki.project_name}\n"]
    for item in wiki.sidebar:
        _render_sidebar_item(item, sidebar_lines, depth=0)

    sidebar_path = out / "_sidebar.md"
    sidebar_path.write_text("\n".join(sidebar_lines) + "\n", encoding="utf-8")

    # Save generation record
    record_path.write_text(json.dumps(generation_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Export metadata for knowledge graph
    _export_metadata(wiki, out)


def _export_metadata(wiki: Wiki, out: Path) -> None:
    """Export metadata for knowledge graph (knowledge relations between wiki items).

    Uses MetadataBuilder from Wiki if available for Qoder-style complete metadata,
    otherwise falls back to simplified metadata extraction.
    """
    meta_dir = out / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)

    # Try to use MetadataBuilder from wiki (Qoder-style complete metadata)
    if wiki.metadata_builder is not None:
        full_metadata = wiki.metadata_builder.build()

        # Add docs list from wiki pages
        docs_list = []
        for page in wiki.pages:
            if page.id not in ("index", "dependencies"):
                docs_list.append({
                    "id": page.id,
                    "title": page.title,
                })
        full_metadata["docs"] = docs_list

        meta_path = meta_dir / "repowiki-metadata.json"
        meta_path.write_text(json.dumps(full_metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    # Fallback: build simplified metadata without MetadataBuilder
    knowledge_relations = []
    for page in wiki.pages:
        if page.parent_id:
            knowledge_relations.append({
                "id": len(knowledge_relations) + 1,
                "source_id": page.parent_id.replace("category/", "").replace("docs/", ""),
                "target_id": page.id.replace("category/", "").replace("docs/", ""),
                "source_type": "WIKI_ITEM",
                "target_type": "WIKI_ITEM",
                "relationship_type": "PARENT_CHILD",
                "extra": f"Wiki parent-child relationship: {page.parent_id} -> {page.id}",
            })

    # Build docs list
    docs_list = []
    for page in wiki.pages:
        if page.id not in ("index", "dependencies"):
            docs_list.append({
                "id": page.id,
                "title": page.title,
            })

    metadata = {
        "knowledge_relations": knowledge_relations,
        "docs": docs_list,
    }

    meta_path = meta_dir / "repowiki-metadata.json"
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def _render_sidebar_item(item: SidebarItem, lines: list[str], depth: int) -> None:
    """Recursively render sidebar items with proper indentation for nested levels."""
    indent = "  " * depth
    if item.page_id:
        # Convert page_id path to proper content path (e.g., category/核心架构/核心组件详解 -> content/category/核心架构/核心组件详解.md)
        content_path = item.page_id.replace("/", "\\") if "\\" in item.page_id or "/" in item.page_id else item.page_id
        lines.append(f"{indent}- [{item.title}](content/{content_path}.md)")
    else:
        lines.append(f"{indent}- **{item.title}**")

    for child in item.children:
        _render_sidebar_item(child, lines, depth + 1)
