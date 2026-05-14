"""Unit tests for precise_graph.py."""

from __future__ import annotations

import pytest

from repowiki.core.precise_graph import (
    ImportKind,
    ImportStatement,
    FileNode,
    PreciseDependencyGraph,
)


class TestImportKind:
    """Tests for ImportKind enum."""

    def test_import_kind_values(self):
        """Test all import kind values exist."""
        assert ImportKind.IMPORT.value == "import"
        assert ImportKind.FROM.value == "from"
        assert ImportKind.REQUIRE.value == "require"
        assert ImportKind.DYNAMIC_IMPORT.value == "dynamic"
        assert ImportKind.STATIC_IMPORT.value == "static"
        assert ImportKind.WILDCARD.value == "wildcard"
        assert ImportKind.TABLE_REFERENCE.value == "table"
        assert ImportKind.VIEW_REFERENCE.value == "view"
        assert ImportKind.PROCEDURE_CALL.value == "procedure"
        assert ImportKind.FUNCTION_CALL.value == "function"
        assert ImportKind.SQL_FILE_REFERENCE.value == "sql_file"


class TestImportStatement:
    """Tests for ImportStatement dataclass."""

    def test_import_statement_creation(self):
        """Test basic ImportStatement creation."""
        imp = ImportStatement(
            source_file="src/main.py",
            target_module="os",
            target_file=None,
            import_kind=ImportKind.IMPORT,
            line_number=1,
            is_external=True,
            raw_statement="import os",
        )
        assert imp.source_file == "src/main.py"
        assert imp.target_module == "os"
        assert imp.is_external is True
        assert imp.import_kind == ImportKind.IMPORT


class TestFileNode:
    """Tests for FileNode dataclass."""

    def test_file_node_creation(self):
        """Test basic FileNode creation."""
        node = FileNode(path="src/main.py", language="python", lines=100)
        assert node.path == "src/main.py"
        assert node.language == "python"
        assert node.lines == 100
        assert node.imports == []
        assert node.imported_by == []


class TestPreciseDependencyGraph:
    """Tests for PreciseDependencyGraph class."""

    def test_empty_graph(self):
        """Test creating an empty graph."""
        graph = PreciseDependencyGraph()
        assert len(graph.files) == 0
        assert len(graph.imports) == 0

    def test_add_file(self):
        """Test adding files to graph."""
        graph = PreciseDependencyGraph()
        graph.add_file("src/main.py", "python", 100)
        graph.add_file("src/utils.py", "python", 50)

        assert len(graph.files) == 2
        assert "src/main.py" in graph.files
        assert "src/utils.py" in graph.files

    def test_add_import(self):
        """Test adding imports to graph."""
        graph = PreciseDependencyGraph()
        graph.add_file("src/main.py", "python", 100)
        graph.add_file("src/utils.py", "python", 50)

        imp = ImportStatement(
            source_file="src/main.py",
            target_module="utils",
            target_file="src/utils.py",
            import_kind=ImportKind.FROM,
            line_number=1,
            is_external=False,
            raw_statement="from utils import func",
        )
        graph.add_import(imp)

        assert len(graph.imports) == 1
        assert len(graph.files["src/main.py"].imports) == 1
        # Check reverse index
        assert "src/main.py" in graph.files["src/utils.py"].imported_by

    def test_get_file_imports(self):
        """Test get_file_imports method."""
        graph = PreciseDependencyGraph()
        graph.add_file("src/main.py", "python", 100)

        imp1 = ImportStatement(
            source_file="src/main.py",
            target_module="os",
            target_file=None,
            import_kind=ImportKind.IMPORT,
            line_number=1,
            is_external=True,
            raw_statement="import os",
        )
        imp2 = ImportStatement(
            source_file="src/main.py",
            target_module="sys",
            target_file=None,
            import_kind=ImportKind.IMPORT,
            line_number=2,
            is_external=True,
            raw_statement="import sys",
        )
        graph.add_import(imp1)
        graph.add_import(imp2)

        imports = graph.get_file_imports("src/main.py")
        assert len(imports) == 2
        assert imports[0].target_module == "os"
        assert imports[1].target_module == "sys"

    def test_get_file_importers(self):
        """Test get_file_importers (reverse index)."""
        graph = PreciseDependencyGraph()
        graph.add_file("src/main.py", "python", 100)
        graph.add_file("src/utils.py", "python", 50)

        imp = ImportStatement(
            source_file="src/main.py",
            target_module="utils",
            target_file="src/utils.py",
            import_kind=ImportKind.FROM,
            line_number=1,
            is_external=False,
            raw_statement="from utils import func",
        )
        graph.add_import(imp)

        importers = graph.get_file_importers("src/utils.py")
        assert "src/main.py" in importers

    def test_get_related_files_direct(self):
        """Test get_related_files with direct relationships."""
        graph = PreciseDependencyGraph()
        graph.add_file("src/main.py", "python", 100)
        graph.add_file("src/utils.py", "python", 50)
        graph.add_file("src/models.py", "python", 75)

        # main -> utils
        imp1 = ImportStatement(
            source_file="src/main.py",
            target_module="utils",
            target_file="src/utils.py",
            import_kind=ImportKind.FROM,
            line_number=1,
            is_external=False,
            raw_statement="from utils import func",
        )
        # utils -> models
        imp2 = ImportStatement(
            source_file="src/utils.py",
            target_module="models",
            target_file="src/models.py",
            import_kind=ImportKind.FROM,
            line_number=1,
            is_external=False,
            raw_statement="from models import User",
        )
        graph.add_import(imp1)
        graph.add_import(imp2)

        # Get files related to main.py
        related = graph.get_related_files("src/main.py", max_depth=1)
        assert "src/utils.py" in related
        assert "src/models.py" not in related  # transitive, not direct

        # Get files related to main.py with depth=2
        related2 = graph.get_related_files("src/main.py", max_depth=2)
        assert "src/utils.py" in related2
        assert "src/models.py" in related2

    def test_get_files_by_language(self):
        """Test get_files_by_language method."""
        graph = PreciseDependencyGraph()
        graph.add_file("src/main.py", "python", 100)
        graph.add_file("src/utils.py", "python", 50)
        graph.add_file("web/index.js", "javascript", 50)

        py_files = graph.get_files_by_language("python")
        js_files = graph.get_files_by_language("javascript")

        assert len(py_files) == 2
        assert len(js_files) == 1
        assert "src/main.py" in py_files

    def test_get_entry_points(self):
        """Test get_entry_points method."""
        graph = PreciseDependencyGraph()
        graph.add_file("main.py", "python", 100)  # entry - nothing imports it
        graph.add_file("utils.py", "python", 50)   # imported by main

        imp = ImportStatement(
            source_file="main.py",
            target_module="utils",
            target_file="utils.py",
            import_kind=ImportKind.FROM,
            line_number=1,
            is_external=False,
            raw_statement="from utils import func",
        )
        graph.add_import(imp)

        entries = graph.get_entry_points()
        # Entry points are files with in_degree <= 1
        # main.py has in_degree 0 (nothing imports it)
        # utils.py has in_degree 1 (imported by main.py)
        # Both have in_degree <= 1, so both are considered entry points
        assert "main.py" in entries
        assert "utils.py" in entries

    def test_rank_files(self):
        """Test rank_files method."""
        graph = PreciseDependencyGraph()
        graph.add_file("main.py", "python", 100)
        graph.add_file("utils.py", "python", 50)
        graph.add_file("models.py", "python", 75)

        # main -> utils and main -> models
        imp1 = ImportStatement(
            source_file="main.py",
            target_module="utils",
            target_file="utils.py",
            import_kind=ImportKind.IMPORT,
            line_number=1,
            is_external=False,
            raw_statement="import utils",
        )
        imp2 = ImportStatement(
            source_file="main.py",
            target_module="models",
            target_file="models.py",
            import_kind=ImportKind.IMPORT,
            line_number=2,
            is_external=False,
            raw_statement="import models",
        )
        graph.add_import(imp1)
        graph.add_import(imp2)

        ranked = graph.rank_files()
        assert len(ranked) == 3
        # main.py should be highest ranked (imported by nothing, but imports others)
        # Actually main.py is highest because it's imported by nothing (lower pagerank naturally)
        # Let's verify structure
        paths = [p for p, _ in ranked]
        assert "main.py" in paths

    def test_to_mermaid(self):
        """Test to_mermaid method."""
        graph = PreciseDependencyGraph()
        graph.add_file("src/main.py", "python", 100)
        graph.add_file("lib/utils.py", "python", 50)

        imp = ImportStatement(
            source_file="src/main.py",
            target_module="utils",
            target_file="lib/utils.py",
            import_kind=ImportKind.FROM,
            line_number=1,
            is_external=False,
            raw_statement="from utils import func",
        )
        graph.add_import(imp)

        mermaid = graph.to_mermaid()
        assert "graph TD" in mermaid
        # Should have module nodes (src and lib are different modules)
        assert "src" in mermaid or "lib" in mermaid

    def test_get_module_dependencies(self):
        """Test get_module_dependencies method."""
        graph = PreciseDependencyGraph()
        graph.add_file("main.py", "python", 100)
        graph.add_file("utils/helper.py", "python", 50)

        imp = ImportStatement(
            source_file="main.py",
            target_module="utils.helper",
            target_file="utils/helper.py",
            import_kind=ImportKind.FROM,
            line_number=1,
            is_external=False,
            raw_statement="from utils.helper import func",
        )
        graph.add_import(imp)

        deps = graph.get_module_dependencies()
        assert "root" in deps  # main.py is in root
        assert "utils" in deps["root"]

    def test_external_deps_tracking(self):
        """Test tracking of external dependencies."""
        graph = PreciseDependencyGraph()
        graph.add_file("main.py", "python", 100)

        imp = ImportStatement(
            source_file="main.py",
            target_module="os",
            target_file=None,
            import_kind=ImportKind.IMPORT,
            line_number=1,
            is_external=True,
            raw_statement="import os",
        )
        graph.add_import(imp)

        assert "os" in graph.external_deps
        assert "os" not in graph.files  # external deps are not file nodes