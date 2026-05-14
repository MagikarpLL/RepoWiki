"""dependency graph construction and PageRank ranking.

This module provides backward compatibility through the DependencyGraph class,
which delegates to PreciseDependencyGraph while maintaining the original interface.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import networkx as nx

from repowiki.core.models import ProjectContext
from repowiki.core.precise_graph import PreciseDependencyGraph
from repowiki.core.parsers import create_parser_registry


class DependencyGraph:
    """File dependency graph with PageRank scoring.

    This class provides backward compatibility by wrapping PreciseDependencyGraph.
    Internally, it uses the new parser registry for precise AST-based parsing.
    """

    def __init__(self, precise_graph: Optional[PreciseDependencyGraph] = None):
        """Initialize the dependency graph.

        Args:
            precise_graph: Optional PreciseDependencyGraph to wrap.
                          If None, will be built via build_from_project().
        """
        self._precise = precise_graph or PreciseDependencyGraph()
        self.graph = self._to_networkx()

    @classmethod
    def build_from_project(cls, project: ProjectContext) -> DependencyGraph:
        """Build dependency graph from a project.

        Args:
            project: ProjectContext with files to analyze

        Returns:
            DependencyGraph instance
        """
        registry = create_parser_registry()
        path_set = {f.path for f in project.files}

        # Build files list for PreciseDependencyGraph
        files = [
            {
                "path": f.path,
                "language": f.language,
                "lines": f.lines,
                "content": f.content or f.preview,
            }
            for f in project.files
        ]

        # Create PreciseDependencyGraph using the parser registry
        precise = PreciseDependencyGraph()

        # Add all file nodes
        for f in files:
            precise.add_file(f["path"], f["language"], f["lines"])

        # Parse imports using the registry and create edges
        for f in files:
            content = f.get("content") or f.get("preview", "")
            if not content:
                continue

            imports = registry.parse(content, f["language"], f["path"])
            for imp in imports:
                from repowiki.core.precise_graph import ImportKind

                # Convert string kind to ImportKind enum
                kind_mapping = {
                    "import": ImportKind.IMPORT,
                    "from": ImportKind.FROM,
                    "require": ImportKind.REQUIRE,
                    "static": ImportKind.STATIC_IMPORT,
                    "wildcard": ImportKind.WILDCARD,
                    "table": ImportKind.TABLE_REFERENCE,
                    "view": ImportKind.VIEW_REFERENCE,
                    "procedure": ImportKind.PROCEDURE_CALL,
                    "function": ImportKind.FUNCTION_CALL,
                    "sql_file": ImportKind.SQL_FILE_REFERENCE,
                }
                import_kind = kind_mapping.get(imp.kind, ImportKind.IMPORT)

                # Resolve target file
                target_file = registry.resolve(
                    imp.module, f["path"], f["language"], path_set
                )

                from repowiki.core.precise_graph import ImportStatement

                precise.add_import(
                    ImportStatement(
                        source_file=f["path"],
                        target_module=imp.module,
                        target_file=target_file,
                        import_kind=import_kind,
                        line_number=imp.line,
                        is_external=imp.is_external,
                        raw_statement=imp.raw,
                    )
                )

        return cls(precise_graph=precise)

    def _to_networkx(self) -> nx.DiGraph:
        """Convert to NetworkX DiGraph for backward compatibility.

        Returns:
            nx.DiGraph with nodes and edges
        """
        g = nx.DiGraph()
        for path, node in self._precise.files.items():
            g.add_node(path, language=node.language, lines=node.lines)
        for imp in self._precise.imports:
            if imp.target_file and imp.source_file != imp.target_file:
                g.add_edge(imp.source_file, imp.target_file)
        return g

    def rank_files(self) -> list[tuple[str, float]]:
        """Return files ranked by PageRank (most important first).

        Returns:
            List of (file_path, score) tuples sorted by score descending
        """
        return self._precise.rank_files()

    def get_core_files(self, top_n: int = 10) -> list[str]:
        """Get top N most important files by PageRank.

        Args:
            top_n: Number of files to return

        Returns:
            List of file paths
        """
        return self._precise.get_core_files(top_n)

    def get_module_dependencies(self) -> dict[str, set[str]]:
        """Get edges between top-level directory modules.

        Returns:
            Dict mapping module name to set of dependent modules
        """
        return self._precise.get_module_dependencies()

    def to_mermaid(self) -> str:
        """Generate a Mermaid flowchart of inter-module dependencies.

        Returns:
            Mermaid diagram string
        """
        return self._precise.to_mermaid()

    def get_entry_points(self) -> list[str]:
        """Get files with zero or very few incoming edges (likely entry points).

        Returns:
            List of file paths
        """
        return self._precise.get_entry_points()

    def get_related_files(self, file_path: str, max_depth: int = 1) -> set[str]:
        """Get all files related to a specific file.

        Args:
            file_path: Starting file path
            max_depth: Maximum traversal depth

        Returns:
            Set of related file paths
        """
        return self._precise.get_related_files(file_path, max_depth)

    def get_file_imports(self, file_path: str) -> list[dict]:
        """Get all imports from a specific file.

        Args:
            file_path: File path

        Returns:
            List of import dicts with module, kind, line, is_external
        """
        imports = self._precise.get_file_imports(file_path)
        return [
            {
                "module": imp.target_module,
                "kind": imp.import_kind.value,
                "line": imp.line_number,
                "is_external": imp.is_external,
            }
            for imp in imports
        ]

    def get_file_importers(self, file_path: str) -> list[str]:
        """Get all files that import a specific file.

        Args:
            file_path: Target file path

        Returns:
            List of source file paths
        """
        return self._precise.get_file_importers(file_path)


# Keep helper functions for backward compatibility
def _get_module(path: str) -> str:
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


def _mermaid_id(name: str) -> str:
    """Convert name to valid Mermaid node ID.

    Args:
        name: Original name

    Returns:
        Sanitized Mermaid ID
    """
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def _resolve_import(
    import_path: str,
    source_file: str,
    language: str,
    known_paths: set[str],
) -> str | None:
    """Resolve import path to actual file path.

    Args:
        import_path: Import path string
        source_file: Source file path
        language: Programming language
        known_paths: Set of known file paths

    Returns:
        Resolved file path or None
    """
    from repowiki.core.parsers import resolve_import

    return resolve_import(import_path, source_file, language, known_paths)