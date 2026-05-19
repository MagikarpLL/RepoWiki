"""Metadata builder for Qoder-style wiki output."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class WikiItemMetadata:
    """Metadata for a wiki item."""

    id: str
    catalog_id: str
    title: str
    description: str
    extend: str = "{}"
    progress_status: str = "completed"
    parent_id: Optional[str] = None
    gmt_create: str = ""
    gmt_modified: str = ""

    def __post_init__(self):
        now = datetime.now().isoformat()
        if not self.gmt_create:
            self.gmt_create = now
        if not self.gmt_modified:
            self.gmt_modified = now

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "catalog_id": self.catalog_id,
            "title": self.title,
            "description": self.description,
            "extend": self.extend,
            "progress_status": self.progress_status,
            "parent_id": self.parent_id,
            "gmt_create": self.gmt_create,
            "gmt_modified": self.gmt_modified,
        }


@dataclass
class WikiCatalogMetadata:
    """Metadata for a wiki catalog (directory)."""

    id: str
    name: str
    parent_id: Optional[str] = None
    gmt_create: str = ""
    gmt_modified: str = ""

    def __post_init__(self):
        now = datetime.now().isoformat()
        if not self.gmt_create:
            self.gmt_create = now
        if not self.gmt_modified:
            self.gmt_modified = now

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "parent_id": self.parent_id,
            "gmt_create": self.gmt_create,
            "gmt_modified": self.gmt_modified,
        }


@dataclass
class KnowledgeRelationMetadata:
    """Metadata for a knowledge relation between wiki items."""

    id: int
    source_id: str
    target_id: str
    source_type: str = "WIKI_ITEM"
    target_type: str = "WIKI_ITEM"
    relationship_type: str = "PARENT_CHILD"
    extra: str = ""
    gmt_create: str = ""
    gmt_modified: str = ""

    def __post_init__(self):
        now = datetime.now().isoformat()
        if not self.gmt_create:
            self.gmt_create = now
        if not self.gmt_modified:
            self.gmt_modified = now

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "source_type": self.source_type,
            "target_type": self.target_type,
            "relationship_type": self.relationship_type,
            "extra": self.extra,
            "gmt_create": self.gmt_create,
            "gmt_modified": self.gmt_modified,
        }


class MetadataBuilder:
    """
    Builder for constructing Qoder-style metadata.

    Creates the metadata structure with:
    - knowledge_relations: Relationships between wiki items
    - wiki_catalogs: Directory structure
    - wiki_items: Individual wiki pages
    - wiki_overview: Project overview
    - wiki_repo: Repository information
    """

    def __init__(self, project_name: str):
        """
        Initialize MetadataBuilder.

        Args:
            project_name: Name of the project
        """
        self.project_name = project_name
        self.items: list[WikiItemMetadata] = []
        self.catalogs: list[WikiCatalogMetadata] = []
        self.relations: list[KnowledgeRelationMetadata] = []

        # Create root catalog
        self._root_catalog_id = str(uuid.uuid4())
        self.catalogs.append(WikiCatalogMetadata(
            id=self._root_catalog_id,
            name=project_name,
        ))

        # Track relation IDs
        self._relation_id_counter = 1

    # ========== Catalog Operations ==========

    def create_catalog(self, name: str, parent_id: Optional[str] = None) -> WikiCatalogMetadata:
        """
        Create a new catalog.

        Args:
            name: Catalog name
            parent_id: Optional parent catalog ID

        Returns:
            WikiCatalogMetadata instance
        """
        catalog = WikiCatalogMetadata(
            id=str(uuid.uuid4()),
            name=name,
            parent_id=parent_id or self._root_catalog_id,
        )
        self.catalogs.append(catalog)
        return catalog

    def get_or_create_catalog(self, name: str, parent_id: Optional[str] = None) -> str:
        """
        Get existing catalog by name or create new one.

        Args:
            name: Catalog name
            parent_id: Optional parent catalog ID

        Returns:
            Catalog ID
        """
        parent = parent_id or self._root_catalog_id

        # Look for existing catalog with same name and parent
        for cat in self.catalogs:
            if cat.name == name and cat.parent_id == parent:
                return cat.id

        # Create new
        catalog = self.create_catalog(name, parent)
        return catalog.id

    # ========== WikiItem Operations ==========

    def create_item(
        self,
        title: str,
        description: str,
        catalog_id: Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> WikiItemMetadata:
        """
        Create a new wiki item.

        Args:
            title: Item title
            description: Item description
            catalog_id: Optional catalog ID (uses root if None)
            parent_id: Optional parent item ID

        Returns:
            WikiItemMetadata instance
        """
        item = WikiItemMetadata(
            id=str(uuid.uuid4()),
            catalog_id=catalog_id or self._root_catalog_id,
            title=title,
            description=description,
            parent_id=parent_id,
        )
        self.items.append(item)
        return item

    def add_knowledge_relation(
        self,
        source_id: str,
        target_id: str,
        relationship_type: str = "PARENT_CHILD",
        extra: str = "",
    ) -> None:
        """
        Add a knowledge relation between two items.

        Args:
            source_id: Source item ID
            target_id: Target item ID
            relationship_type: Type of relationship
            extra: Additional information
        """
        relation = KnowledgeRelationMetadata(
            id=self._relation_id_counter,
            source_id=source_id,
            target_id=target_id,
            relationship_type=relationship_type,
            extra=extra or f"Wiki {relationship_type.lower()}: {source_id} -> {target_id}",
        )
        self.relations.append(relation)
        self._relation_id_counter += 1

    # ========== Build Operations ==========

    def build(self) -> dict:
        """
        Build the complete metadata dictionary.

        Returns:
            Dictionary with all metadata sections
        """
        now = datetime.now().isoformat()

        return {
            "knowledge_relations": [r.to_dict() for r in self.relations],
            "wiki_catalogs": [c.to_dict() for c in self.catalogs],
            "wiki_items": [i.to_dict() for i in self.items],
            "wiki_overview": {
                "content": f"# {self.project_name}\n\nProject documentation generated by RepoWiki."
            },
            "wiki_repo": {
                "id": str(uuid.uuid4()),
                "name": self.project_name,
                "progress_status": "completed",
                "wiki_present_status": "COMPLETED",
                "optimized_catalog": "",
            },
        }

    def save(self, filepath: str) -> None:
        """
        Save metadata to a JSON file.

        Args:
            filepath: Output file path
        """
        metadata = self.build()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

    def load(self, filepath: str) -> None:
        """
        Load metadata from a JSON file.

        Args:
            filepath: Input file path
        """
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Restore items
        self.items = [WikiItemMetadata(**item) for item in data.get("wiki_items", [])]

        # Restore catalogs
        self.catalogs = [WikiCatalogMetadata(**cat) for cat in data.get("wiki_catalogs", [])]

        # Restore relations
        self.relations = [KnowledgeRelationMetadata(**rel) for rel in data.get("knowledge_relations", [])]

        # Update relation counter
        if self.relations:
            self._relation_id_counter = max(r.id for r in self.relations) + 1

    # ========== Utility Methods ==========

    def get_item_by_title(self, title: str) -> Optional[WikiItemMetadata]:
        """Get a wiki item by its title."""
        for item in self.items:
            if item.title == title:
                return item
        return None

    def get_items_by_catalog(self, catalog_id: str) -> list[WikiItemMetadata]:
        """Get all wiki items in a catalog."""
        return [item for item in self.items if item.catalog_id == catalog_id]

    def get_child_items(self, parent_id: str) -> list[WikiItemMetadata]:
        """Get all child items of a parent item."""
        return [item for item in self.items if item.parent_id == parent_id]

    def get_catalog_tree(self) -> dict:
        """Get the catalog tree structure."""
        tree = {}

        def build_tree(catalog_id: str) -> dict:
            node = {}
            for cat in self.catalogs:
                if cat.id == catalog_id:
                    node["id"] = cat.id
                    node["name"] = cat.name
                    break

            children = [c for c in self.catalogs if c.parent_id == catalog_id]
            if children:
                node["children"] = [build_tree(c.id) for c in children]

            return node

        # Build from root
        for cat in self.catalogs:
            if cat.parent_id is None:
                tree = build_tree(cat.id)
                break

        return tree

    def summary(self) -> str:
        """Get a summary of the metadata."""
        lines = [
            f"MetadataBuilder Summary:",
            f"  Project: {self.project_name}",
            f"  Catalogs: {len(self.catalogs)}",
            f"  Items: {len(self.items)}",
            f"  Relations: {len(self.relations)}",
        ]
        return "\n".join(lines)


def create_metadata_from_symbols(
    project_name: str,
    symbols: list,
    module_structure: dict[str, list[str]] = None,
) -> dict:
    """
    Convenience function to create metadata from symbol list.

    Args:
        project_name: Project name
        symbols: List of SymbolNode
        module_structure: Optional dict mapping modules to file paths

    Returns:
        Metadata dictionary
    """
    builder = MetadataBuilder(project_name)

    # Create module catalogs
    if module_structure:
        for module_name in module_structure.keys():
            builder.get_or_create_catalog(module_name)

    # Create items for each symbol
    for symbol in symbols[:100]:  # Limit to 100
        catalog_id = builder.get_or_create_catalog(symbol.file.split("/")[0] if "/" in symbol.file else "root")
        builder.create_item(
            title=symbol.name,
            description=f"{symbol.kind.value}: {symbol.name}",
            catalog_id=catalog_id,
        )

    return builder.build()