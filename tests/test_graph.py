"""Unit tests for graph.py backward compatibility."""

from __future__ import annotations

import pytest

from repowiki.core.graph import DependencyGraph
from repowiki.core.models import ProjectContext, FileInfo


class TestDependencyGraphBackwardCompatibility:
    """Tests for DependencyGraph backward compatibility."""

    def test_build_from_project_creates_graph(self):
        """Test build_from_project creates a valid graph."""
        files = [
            FileInfo(path="main.py", language="python", lines=100, size=100, content="import os\nimport sys", preview="import os"),
            FileInfo(path="utils.py", language="python", lines=50, size=50, content="import re", preview="import re"),
        ]
        project = ProjectContext(name="test", root=".", files=files)

        graph = DependencyGraph.build_from_project(project)

        assert graph.graph is not None
        assert len(graph.graph.nodes) == 2

    def test_rank_files_returns_list(self):
        """Test rank_files returns list of tuples."""
        files = [
            FileInfo(path="main.py", language="python", lines=100, size=100, content="import os", preview="import os"),
            FileInfo(path="utils.py", language="python", lines=50, size=50, content="import re", preview="import re"),
        ]
        project = ProjectContext(name="test", root=".", files=files)

        graph = DependencyGraph.build_from_project(project)
        ranked = graph.rank_files()

        assert isinstance(ranked, list)
        if ranked:
            assert isinstance(ranked[0], tuple)
            assert len(ranked[0]) == 2

    def test_get_core_files_returns_paths(self):
        """Test get_core_files returns list of paths."""
        files = [
            FileInfo(path="main.py", language="python", lines=100, size=100, content="import os", preview="import os"),
            FileInfo(path="utils.py", language="python", lines=50, size=50, content="import re", preview="import re"),
        ]
        project = ProjectContext(name="test", root=".", files=files)

        graph = DependencyGraph.build_from_project(project)
        core = graph.get_core_files(top_n=1)

        assert isinstance(core, list)
        if core:
            assert isinstance(core[0], str)

    def test_to_mermaid_returns_string(self):
        """Test to_mermaid returns valid mermaid string."""
        files = [
            FileInfo(path="main.py", language="python", lines=100, size=100, content="import utils", preview="import utils"),
            FileInfo(path="utils.py", language="python", lines=50, size=50, content="", preview=""),
        ]
        project = ProjectContext(name="test", root=".", files=files)

        graph = DependencyGraph.build_from_project(project)
        mermaid = graph.to_mermaid()

        assert isinstance(mermaid, str)
        if mermaid:
            assert "graph TD" in mermaid

    def test_get_entry_points(self):
        """Test get_entry_points returns likely entry points."""
        files = [
            FileInfo(path="main.py", language="python", lines=100, size=100, content="import utils", preview="import utils"),
            FileInfo(path="utils.py", language="python", lines=50, size=50, content="", preview=""),
        ]
        project = ProjectContext(name="test", root=".", files=files)

        graph = DependencyGraph.build_from_project(project)
        entries = graph.get_entry_points()

        assert isinstance(entries, list)

    def test_get_related_files(self):
        """Test get_related_files returns related file paths."""
        files = [
            FileInfo(path="main.py", language="python", lines=100, size=100, content="import utils", preview="import utils"),
            FileInfo(path="utils.py", language="python", lines=50, size=50, content="import os", preview="import os"),
        ]
        project = ProjectContext(name="test", root=".", files=files)

        graph = DependencyGraph.build_from_project(project)
        related = graph.get_related_files("main.py", max_depth=1)

        assert isinstance(related, set)
        # utils.py should be related to main.py
        assert "utils.py" in related

    def test_get_file_importers(self):
        """Test get_file_importers returns files that import the target."""
        files = [
            FileInfo(path="main.py", language="python", lines=100, size=100, content="import utils", preview="import utils"),
            FileInfo(path="utils.py", language="python", lines=50, size=50, content="", preview=""),
        ]
        project = ProjectContext(name="test", root=".", files=files)

        graph = DependencyGraph.build_from_project(project)
        importers = graph.get_file_importers("utils.py")

        assert isinstance(importers, list)
        assert "main.py" in importers

    def test_networkx_graph_has_nodes(self):
        """Test internal networkx graph has correct nodes."""
        files = [
            FileInfo(path="main.py", language="python", lines=100, size=100, content="import os", preview="import os"),
        ]
        project = ProjectContext(name="test", root=".", files=files)

        graph = DependencyGraph.build_from_project(project)

        assert len(graph.graph.nodes) == 1
        assert "main.py" in graph.graph.nodes
        assert graph.graph.nodes["main.py"]["language"] == "python"
        assert graph.graph.nodes["main.py"]["lines"] == 100

    def test_empty_project(self):
        """Test handling empty project."""
        project = ProjectContext(name="test", root=".", files=[])
        graph = DependencyGraph.build_from_project(project)

        assert len(graph.graph.nodes) == 0
        assert graph.rank_files() == []
        assert graph.get_core_files() == []


class TestDependencyGraphEdgeCases:
    """Tests for edge cases in DependencyGraph."""

    def test_file_without_content(self):
        """Test file with empty content."""
        files = [
            FileInfo(path="empty.py", language="python", lines=0, size=0, content="", preview=""),
        ]
        project = ProjectContext(name="test", root=".", files=files)
        graph = DependencyGraph.build_from_project(project)

        assert len(graph.graph.nodes) == 1

    def test_unsupported_language(self):
        """Test file with unsupported language."""
        files = [
            FileInfo(path="main.xyz", language="unknown", lines=100, size=100, content="import something", preview="import something"),
        ]
        project = ProjectContext(name="test", root=".", files=files)
        graph = DependencyGraph.build_from_project(project)

        # Should not crash, but may have no edges
        assert len(graph.graph.nodes) == 1

    def test_external_imports_dont_create_nodes(self):
        """Test that external imports don't create nodes in graph."""
        files = [
            FileInfo(path="main.py", language="python", lines=100, size=100, content="import os\nimport sys", preview="import os"),
        ]
        project = ProjectContext(name="test", root=".", files=files)

        graph = DependencyGraph.build_from_project(project)

        # os and sys are external, so no edges should be created
        assert len(graph.graph.edges) == 0

    def test_multiple_files_same_import(self):
        """Test multiple files importing same module."""
        files = [
            FileInfo(path="main.py", language="python", lines=100, size=100, content="import utils", preview="import utils"),
            FileInfo(path="other.py", language="python", lines=50, size=50, content="import utils", preview="import utils"),
            FileInfo(path="utils.py", language="python", lines=25, size=25, content="", preview=""),
        ]
        project = ProjectContext(name="test", root=".", files=files)

        graph = DependencyGraph.build_from_project(project)

        # Both main.py and other.py should have edges to utils.py
        assert ("main.py", "utils.py") in graph.graph.edges
        assert ("other.py", "utils.py") in graph.graph.edges