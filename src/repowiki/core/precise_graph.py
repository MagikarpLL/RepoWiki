"""Precise dependency graph with exact AST-based parsing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import networkx as nx


class ImportKind(Enum):
    """Import/dependency type enumeration."""

    # Python
    IMPORT = "import"  # import os.path
    FROM = "from"  # from os import path

    # JavaScript/TypeScript
    REQUIRE = "require"  # require('fs')
    DYNAMIC_IMPORT = "dynamic"  # import('path')

    # Java
    STATIC_IMPORT = "static"  # import static java.lang.Math.PI
    WILDCARD = "wildcard"  # import java.util.*

    # SQL
    TABLE_REFERENCE = "table"  # SELECT FROM table
    VIEW_REFERENCE = "view"  # CREATE VIEW ... AS SELECT FROM view
    PROCEDURE_CALL = "procedure"  # CALL proc_name()
    FUNCTION_CALL = "function"  # SELECT func()
    SQL_FILE_REFERENCE = "sql_file"  # \i other.sql


@dataclass
class ImportStatement:
    """Precisely parsed import/reference statement."""

    source_file: str  # Source file path
    target_module: str  # Target module/package name
    target_file: Optional[str]  # Resolved target file path (None for external deps)
    import_kind: ImportKind
    line_number: int
    is_external: bool  # Is external dependency (third-party/system lib)
    raw_statement: str  # Original statement (for debugging)


@dataclass
class FileNode:
    """File node in the dependency graph."""

    path: str
    language: str
    lines: int
    imports: list[ImportStatement] = field(default_factory=list)
    imported_by: list[str] = field(default_factory=list)  # Reverse index
    parse_error: Optional[str] = None


class PreciseDependencyGraph:
    """Precise dependency graph with AST-based parsing."""

    def __init__(self):
        self.files: dict[str, FileNode] = {}
        self.imports: list[ImportStatement] = []
        self.external_deps: set[str] = set()
        self._importers_index: dict[str, list[str]] = {}  # Reverse index

    # ========== Graph Building Methods ==========

    def add_file(self, path: str, language: str, lines: int) -> None:
        """Add a file node to the graph.

        Args:
            path: File path
            language: Programming language
            lines: Number of lines in file
        """
        if path not in self.files:
            self.files[path] = FileNode(path=path, language=language, lines=lines)

    def add_import(self, imp: ImportStatement) -> None:
        """Add an import statement to the graph.

        Args:
            imp: ImportStatement to add
        """
        self.imports.append(imp)

        # Update source file's imports list
        if imp.source_file in self.files:
            self.files[imp.source_file].imports.append(imp)

        # Update target file's imported_by (reverse index)
        if imp.target_file:
            self._importers_index.setdefault(imp.target_file, []).append(imp.source_file)
            if imp.target_file in self.files:
                self.files[imp.target_file].imported_by.append(imp.source_file)

        # Track external dependencies
        if imp.is_external:
            self.external_deps.add(imp.target_module)

    def build_from_project(
        self,
        files: list[dict],
        parse_func: callable,
        resolve_func: callable,
    ) -> None:
        """Build graph from project files.

        Args:
            files: List of FileInfo dicts with path, language, lines, content
            parse_func: Function(source, language, filepath) -> list[ImportInfo]
            resolve_func: Function(module, source_file, language, known_paths) -> str|None
        """
        path_set = {f["path"] for f in files}

        # Add all file nodes
        for f in files:
            self.add_file(f["path"], f["language"], f["lines"])

        # Parse imports and create edges
        for f in files:
            content = f.get("content") or f.get("preview", "")
            if not content:
                continue

            imports = parse_func(content, f["language"], f["path"])
            for imp in imports:
                import_stmt = ImportStatement(
                    source_file=f["path"],
                    target_module=imp["module"],
                    target_file=resolve_func(
                        imp["module"], f["path"], f["language"], path_set
                    ),
                    import_kind=_kind_to_enum(imp["kind"]),
                    line_number=imp["line"],
                    is_external=imp["is_external"],
                    raw_statement=imp["raw"],
                )
                self.add_import(import_stmt)

    # ========== Query Methods ==========

    def get_file_imports(self, file_path: str) -> list[ImportStatement]:
        """Get all imports from a specific file.

        Args:
            file_path: Path to the file

        Returns:
            List of ImportStatement from this file
        """
        return self.files.get(file_path, FileNode(path="", language="", lines=0)).imports

    def get_file_importers(self, file_path: str) -> list[str]:
        """Get all files that import a specific file (reverse index).

        Args:
            file_path: Path to the target file

        Returns:
            List of source file paths that import this file
        """
        return self._importers_index.get(file_path, [])

    def get_related_files(self, file_path: str, max_depth: int = 1) -> set[str]:
        """Get all files related to a specific file.

        Args:
            file_path: Starting file path
            max_depth: Maximum traversal depth (1=direct, 2=transitive)

        Returns:
            Set of related file paths (excluding the starting file)
        """
        related = set()
        visited = set()
        queue = [(file_path, 0)]

        while queue:
            current, depth = queue.pop(0)
            if current in visited or depth > max_depth:
                continue
            visited.add(current)
            if current != file_path:
                related.add(current)

            # BFS: files imported by current + files that import current
            if current in self.files:
                for imp in self.files[current].imports:
                    if imp.target_file and imp.target_file not in visited:
                        queue.append((imp.target_file, depth + 1))
            for importer in self._importers_index.get(current, []):
                if importer not in visited:
                    queue.append((importer, depth + 1))

        return related

    def get_files_by_language(self, language: str) -> list[str]:
        """Get all files of a specific language.

        Args:
            language: Programming language

        Returns:
            List of file paths
        """
        return [
            path for path, node in self.files.items() if node.language == language
        ]

    def get_files_by_module(self, module_name: str) -> list[str]:
        """Get all files belonging to a specific module (top-level directory).

        Args:
            module_name: Module/directory name

        Returns:
            List of file paths in the module
        """
        return [
            path
            for path in self.files
            if path.startswith(f"{module_name}/")
            or Path(path).parts[0] == module_name
        ]

    # ========== Analysis Methods ==========

    def rank_files(self) -> list[tuple[str, float]]:
        """Rank files by importance using PageRank algorithm.

        Returns:
            List of (file_path, score) sorted by score descending
        """
        if not self.files:
            return []

        g = nx.DiGraph()
        for path, node in self.files.items():
            g.add_node(path, language=node.language, lines=node.lines)
        for imp in self.imports:
            if imp.target_file and imp.source_file != imp.target_file:
                g.add_edge(imp.source_file, imp.target_file)

        try:
            scores = nx.pagerank(g, alpha=0.85)
        except Exception:
            # Fallback: uniform scores
            scores = {n: 1.0 / len(g) for n in g.nodes()}
        return sorted(scores.items(), key=lambda x: -x[1])

    def get_core_files(self, top_n: int = 10) -> list[str]:
        """Get the top N most important files by PageRank.

        Args:
            top_n: Number of files to return

        Returns:
            List of file paths
        """
        return [path for path, _ in self.rank_files()[:top_n]]

    def get_entry_points(self) -> list[str]:
        """Get likely entry point files (few incoming edges).

        Returns:
            List of file paths that are likely entry points
        """
        entries = []
        for path in self.files:
            importers = self._importers_index.get(path, [])
            if len(importers) <= 1:
                entries.append(path)
        return entries

    def get_module_dependencies(self) -> dict[str, set[str]]:
        """Get dependencies between top-level modules.

        Returns:
            Dict mapping module name to set of dependent modules
        """
        deps: dict[str, set[str]] = {}
        for imp in self.imports:
            if not imp.target_file or imp.is_external:
                continue
            src_mod = self._get_module(imp.source_file)
            dst_mod = self._get_module(imp.target_file)
            if src_mod != dst_mod:
                deps.setdefault(src_mod, set()).add(dst_mod)
        return deps

    def to_mermaid(self) -> str:
        """Generate Mermaid flowchart of inter-module dependencies.

        Returns:
            Mermaid diagram string
        """
        lines = ["graph TD"]
        mod_deps = self.get_module_dependencies()

        if not mod_deps:
            return ""

        # Module file counts for descriptions
        module_files: dict[str, int] = {}
        for path in self.files:
            mod = self._get_module(path)
            module_files[mod] = module_files.get(mod, 0) + 1

        # Group modules by type
        frontend_mods = set()
        backend_mods = set()
        ui_mods = {"components", "pages", "views", "ui", "frontend", "client", "web"}

        for mod in mod_deps:
            mod_lower = mod.lower()
            if any(ui in mod_lower for ui in ui_mods):
                frontend_mods.add(mod)
            else:
                backend_mods.add(mod)

        # Add subgraphs for better visualization
        if frontend_mods and backend_mods:
            lines.append("  subgraph Frontend")
            for mod in sorted(frontend_mods):
                count = module_files.get(mod, 0)
                s = self._mermaid_id(mod)
                lines.append(f"    {s}[({mod} - {count} files)]")
            lines.append("  end")
            lines.append("  subgraph Backend")
            for mod in sorted(backend_mods):
                if mod not in frontend_mods:
                    count = module_files.get(mod, 0)
                    s = self._mermaid_id(mod)
                    lines.append(f"    {s}[({mod} - {count} files)]")
            lines.append("  end")
            lines.append("")
        else:
            # Simple visualization
            for mod, count in sorted(module_files.items(), key=lambda x: -x[1])[:12]:
                s = self._mermaid_id(mod)
                lines.append(f"  {s}[({mod} - {count} files)]")

        # Add edges
        lines.append("")
        seen_edges = set()
        for src, targets in sorted(mod_deps.items()):
            for dst in sorted(targets):
                edge = (src, dst)
                if edge not in seen_edges:
                    seen_edges.add(edge)
                    s = self._mermaid_id(src)
                    d = self._mermaid_id(dst)
                    lines.append(f"  {s} --> {d}")

        return "\n".join(lines)

    # ========== Private Helper Methods ==========

    def _get_module(self, path: str) -> str:
        """Extract module name (top-level directory) from file path.

        Args:
            path: File path

        Returns:
            Module name
        """
        parts = Path(path).parts
        if len(parts) <= 1:
            return "root"
        mod = parts[0]
        if mod in ("src", "lib", "pkg", "internal", "app") and len(parts) > 2:
            return parts[1]
        return mod

    def _mermaid_id(self, name: str) -> str:
        """Convert name to valid Mermaid node ID.

        Args:
            name: Original name

        Returns:
            Sanitized Mermaid ID
        """
        import re

        return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def _kind_to_enum(kind: str) -> ImportKind:
    """Convert string kind to ImportKind enum.

    Args:
        kind: String representation of import kind

    Returns:
        ImportKind enum value
    """
    mapping = {
        "import": ImportKind.IMPORT,
        "from": ImportKind.FROM,
        "require": ImportKind.REQUIRE,
        "dynamic": ImportKind.DYNAMIC_IMPORT,
        "static": ImportKind.STATIC_IMPORT,
        "wildcard": ImportKind.WILDCARD,
        "table": ImportKind.TABLE_REFERENCE,
        "view": ImportKind.VIEW_REFERENCE,
        "procedure": ImportKind.PROCEDURE_CALL,
        "function": ImportKind.FUNCTION_CALL,
        "sql_file": ImportKind.SQL_FILE_REFERENCE,
    }
    return mapping.get(kind, ImportKind.IMPORT)


def _enum_to_kind(kind: ImportKind) -> str:
    """Convert ImportKind enum to string.

    Args:
        kind: ImportKind enum value

    Returns:
        String representation
    """
    return kind.value