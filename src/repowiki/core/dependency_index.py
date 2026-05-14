"""Dependency index for efficient file relationship queries."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from repowiki.core.precise_graph import PreciseDependencyGraph


class DependencyIndex:
    """Dependency index for efficient file relationship queries.

    This class provides various indices and query methods to find
    related files, files by module/language, and statistics.
    """

    def __init__(self, graph: PreciseDependencyGraph):
        """Initialize the dependency index.

        Args:
            graph: PreciseDependencyGraph to index
        """
        self._graph = graph
        self._build_indices()

    def _build_indices(self) -> None:
        """Build all indices for efficient querying."""
        # Module index: module_name -> list of file paths
        self._module_index: dict[str, list[str]] = {}
        for path in self._graph.files:
            module = self._get_module_name(path)
            self._module_index.setdefault(module, []).append(path)

        # Language index: language -> list of file paths
        self._language_index: dict[str, list[str]] = {}
        for path, node in self._graph.files.items():
            self._language_index.setdefault(node.language, []).append(path)

        # External dependency index: dep_name -> list of source files
        self._external_deps_index: dict[str, list[str]] = {}
        for imp in self._graph.imports:
            if imp.is_external:
                self._external_deps_index.setdefault(imp.target_module, []).append(
                    imp.source_file
                )

    def find_related_files(
        self, file_paths: list[str], max_depth: int = 1
    ) -> set[str]:
        """Find all files related to the given file(s).

        This is the core query interface for finding related files.

        Args:
            file_paths: List of starting file paths
            max_depth: Maximum traversal depth (1=direct, 2=transitive)

        Returns:
            Set of related file paths (excluding the starting files)
        """
        all_related = set()
        for fp in file_paths:
            all_related |= self._graph.get_related_files(fp, max_depth)
        return all_related

    def find_files_in_module(self, module_name: str) -> list[str]:
        """Find all files belonging to a specific module.

        Args:
            module_name: Module/directory name

        Returns:
            List of file paths in the module
        """
        return self._module_index.get(module_name, [])

    def find_files_by_language(self, language: str) -> list[str]:
        """Find all files of a specific language.

        Args:
            language: Programming language

        Returns:
            List of file paths
        """
        return self._language_index.get(language, [])

    def find_files_using_external_dep(self, dep_name: str) -> list[str]:
        """Find all files that use a specific external dependency.

        Args:
            dep_name: External dependency name (e.g., 'numpy', 'react')

        Returns:
            List of source file paths that depend on this external dep
        """
        return self._external_deps_index.get(dep_name, [])

    def find_files_with_imports(self, target_file: str) -> list[str]:
        """Find all files that import a specific target file.

        Args:
            target_file: Target file path

        Returns:
            List of source file paths
        """
        return self._graph.get_file_importers(target_file)

    def find_imports_in_file(self, file_path: str) -> list[str]:
        """Find all imports in a specific file.

        Args:
            file_path: File path

        Returns:
            List of target module names imported by this file
        """
        imports = self._graph.get_file_imports(file_path)
        return [imp.target_module for imp in imports]

    def get_module_name(self, file_path: str) -> str:
        """Get the module name for a file path.

        Args:
            file_path: File path

        Returns:
            Module name
        """
        return self._get_module_name(file_path)

    def get_statistics(self) -> dict:
        """Get dependency graph statistics.

        Returns:
            Dict with statistics about the graph
        """
        return {
            "total_files": len(self._graph.files),
            "total_imports": len(self._graph.imports),
            "external_dependencies": len(self._graph.external_deps),
            "modules": len(self._module_index),
            "languages": len(self._language_index),
            "external_deps_list": sorted(self._graph.external_deps)[:50],
        }

    def get_language_statistics(self) -> dict[str, dict]:
        """Get statistics per language.

        Returns:
            Dict mapping language to statistics dict
        """
        stats = {}
        for lang, files in self._language_index.items():
            import_counts = {}
            for f in files:
                imports = self._graph.get_file_imports(f)
                import_counts[f] = len(imports)
            stats[lang] = {
                "file_count": len(files),
                "total_imports": sum(import_counts.values()),
                "avg_imports_per_file": (
                    sum(import_counts.values()) / len(files) if files else 0
                ),
            }
        return stats

    def get_module_statistics(self) -> dict[str, dict]:
        """Get statistics per module.

        Returns:
            Dict mapping module name to statistics dict
        """
        stats = {}
        for mod, files in self._module_index.items():
            file_count = len(files)
            total_lines = sum(self._graph.files[f].lines for f in files)
            internal_deps = 0
            external_deps = 0
            for f in files:
                for imp in self._graph.get_file_imports(f):
                    if imp.is_external:
                        external_deps += 1
                    else:
                        internal_deps += 1
            stats[mod] = {
                "file_count": file_count,
                "total_lines": total_lines,
                "internal_dependencies": internal_deps,
                "external_dependencies": external_deps,
            }
        return stats

    def search_files(
        self,
        query: str,
        field: str = "path",
        language: Optional[str] = None,
        module: Optional[str] = None,
    ) -> list[str]:
        """Search files by path or other fields.

        Args:
            query: Search query string
            field: Field to search ('path', 'module')
            language: Optional language filter
            module: Optional module filter

        Returns:
            List of matching file paths
        """
        results = []

        # Apply language filter first
        if language:
            candidates = self._language_index.get(language, [])
        else:
            candidates = list(self._graph.files.keys())

        # Apply module filter
        if module:
            module_files = set(self._module_index.get(module, []))
            candidates = [f for f in candidates if f in module_files]

        # Search by path
        if field == "path":
            query_lower = query.lower()
            for f in candidates:
                if query_lower in f.lower():
                    results.append(f)

        return results

    def _get_module_name(self, path: str) -> str:
        """Extract module name (top-level directory) from file path.

        Args:
            path: File path

        Returns:
            Module name
        """
        parts = Path(path).parts
        if len(parts) <= 1:
            return "root"
        return parts[0]


def create_dependency_index(graph: PreciseDependencyGraph) -> DependencyIndex:
    """Create a DependencyIndex from a PreciseDependencyGraph.

    Args:
        graph: PreciseDependencyGraph to index

    Returns:
        DependencyIndex instance
    """
    return DependencyIndex(graph)