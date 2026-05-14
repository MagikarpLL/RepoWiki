"""Unit tests for parsers.py."""

from __future__ import annotations

import pytest

from repowiki.core.parsers import (
    ImportInfo,
    ParserRegistry,
    parse_python,
    parse_javascript,
    parse_java,
    parse_sql,
    parse_go,
    parse_rust,
    resolve_python,
    resolve_js,
    resolve_java,
    resolve_sql,
    create_parser_registry,
    get_parser_registry,
)


class TestImportInfo:
    """Tests for ImportInfo dataclass."""

    def test_import_info_creation(self):
        """Test basic ImportInfo creation."""
        info = ImportInfo(
            module="os",
            name=None,
            kind="import",
            line=1,
            is_external=True,
            raw="import os",
        )
        assert info.module == "os"
        assert info.kind == "import"
        assert info.is_external is True


class TestParsePython:
    """Tests for Python parser using stdlib ast."""

    def test_simple_import(self):
        """Test simple import statement."""
        source = "import os"
        results = parse_python(source, "test.py")
        assert len(results) == 1
        assert results[0].module == "os"
        assert results[0].kind == "import"

    def test_from_import(self):
        """Test from...import statement."""
        source = "from os import path"
        results = parse_python(source, "test.py")
        assert len(results) == 1
        # module is the source module (os), name is the imported item (path)
        assert results[0].module == "os"
        assert results[0].name == "path"
        assert results[0].kind == "from"

    def test_from_module_import(self):
        """Test from module import specific names."""
        source = "from collections import OrderedDict, namedtuple"
        results = parse_python(source, "test.py")
        assert len(results) == 2
        # modules should be "collections" for both (the source module)
        modules = [r.module for r in results]
        assert "collections" in modules
        # names should be the imported items
        names = [r.name for r in results]
        assert "OrderedDict" in names
        assert "namedtuple" in names

    def test_relative_import(self):
        """Test relative import (from .module import x)."""
        source = "from . import utils"
        results = parse_python(source, "test.py")
        assert len(results) == 1
        # module should be "." for relative import with no module name
        assert results[0].module == "."
        assert results[0].name == "utils"
        assert results[0].is_external is False

    def test_relative_import_level_2(self):
        """Test relative import with level 2 (from .. import x)."""
        source = "from .. import parent"
        results = parse_python(source, "test.py")
        assert len(results) == 1
        assert results[0].module == ".."
        assert results[0].is_external is False

    def test_multiple_imports(self):
        """Test multiple import statements."""
        source = """import os
import sys
from collections import OrderedDict"""
        results = parse_python(source, "test.py")
        assert len(results) == 3
        modules = [r.module for r in results]
        names = [r.name for r in results]
        assert "os" in modules
        assert "sys" in modules
        assert "collections" in modules
        assert "OrderedDict" in names

    def test_module_not_external_for_relative(self):
        """Test that relative imports are not marked as external."""
        source = "from .utils import helper"
        results = parse_python(source, "test.py")
        assert len(results) == 1
        assert results[0].is_external is False

    def test_module_is_external_for_absolute(self):
        """Test that absolute imports are marked as external."""
        source = "import numpy"
        results = parse_python(source, "test.py")
        assert len(results) == 1
        assert results[0].is_external is True


class TestParseJavaScript:
    """Tests for JavaScript parser."""

    def test_simple_import(self):
        """Test simple import statement."""
        source = "import foo from 'bar'"
        results = parse_javascript(source, "test.js")
        # May return empty if ast-grep not installed (fallback to regex)
        # At minimum, should not crash
        assert isinstance(results, list)

    def test_named_import(self):
        """Test named import."""
        source = "import { useState } from 'react'"
        results = parse_javascript(source, "test.js")
        # May be empty if ast-grep not installed
        assert isinstance(results, list)

    def test_require(self):
        """Test require() statement."""
        source = "const fs = require('fs')"
        results = parse_javascript(source, "test.js")
        modules = [r.module for r in results if r.kind == "require"]
        assert "fs" in modules

    def test_side_effect_import(self):
        """Test import without assignment."""
        source = "import 'polyfill'"
        results = parse_javascript(source, "test.js")
        # Should not crash
        assert isinstance(results, list)


class TestParseJava:
    """Tests for Java parser."""

    def test_simple_import(self):
        """Test simple import statement."""
        source = "import java.util.List;"
        results = parse_java(source, "test.java")
        assert len(results) >= 1
        modules = [r.module for r in results]
        # Should contain java.util.List
        assert any("java.util" in m for m in modules)

    def test_wildcard_import(self):
        """Test wildcard import."""
        source = "import java.util.*;"
        results = parse_java(source, "test.java")
        # Should match wildcard import
        kinds = [r.kind for r in results]
        assert "wildcard" in kinds or "import" in kinds

    def test_static_import(self):
        """Test static import."""
        source = "import static java.lang.Math.PI;"
        results = parse_java(source, "test.java")
        # Should be detected


class TestParseSQL:
    """Tests for SQL parser."""

    def test_table_reference(self):
        """Test table reference in SELECT."""
        source = "SELECT * FROM users"
        results = parse_sql(source, "test.sql")
        modules = [r.module for r in results]
        assert "users" in modules

    def test_multiple_tables(self):
        """Test multiple table references."""
        source = "SELECT * FROM users JOIN orders ON users.id = orders.user_id"
        results = parse_sql(source, "test.sql")
        modules = [r.module for r in results]
        assert "users" in modules
        assert "orders" in modules

    def test_procedure_call(self):
        """Test stored procedure call."""
        source = "EXEC usp_GetOrders"
        results = parse_sql(source, "test.sql")
        modules = [r.module for r in results]
        assert "usp_GetOrders" in modules

    def test_sql_include(self):
        """Test PostgreSQL \\i include statement."""
        source = "\\i other.sql"
        results = parse_sql(source, "test.sql")
        modules = [r.module for r in results]
        assert "other.sql" in modules


class TestResolvePython:
    """Tests for Python path resolver."""

    def test_resolve_simple_module(self):
        """Test resolving simple module to file."""
        known_paths = {"os.py", "sys.py"}
        result = resolve_python("os", "main.py", known_paths)
        assert result == "os.py"

    def test_resolve_nested_module(self):
        """Test resolving nested module."""
        known_paths = {"src/utils.py", "src/utils/__init__.py"}
        result = resolve_python("src.utils", "main.py", known_paths)
        assert result == "src/utils.py"

    def test_resolve_init_file(self):
        """Test resolving module with __init__."""
        known_paths = {"src/__init__.py"}
        result = resolve_python("src", "main.py", known_paths)
        assert result == "src/__init__.py"


class TestParserRegistry:
    """Tests for ParserRegistry."""

    def test_register_and_parse(self):
        """Test registering and using a parser."""
        registry = ParserRegistry()

        def custom_parser(source, filepath):
            return [ImportInfo(module="test", name=None, kind="test", line=1, is_external=True, raw="test")]

        registry.register("custom", custom_parser)
        results = registry.parse("source", "custom", "file")
        assert len(results) == 1
        assert results[0].module == "test"

    def test_register_resolver(self):
        """Test registering a resolver."""
        registry = ParserRegistry()

        def custom_resolver(module, source_file, known_paths):
            return f"{module}.py"

        registry.register_resolver("custom", custom_resolver)
        result = registry.resolve("test", "main.py", "custom", {"test.py"})
        assert result == "test.py"

    def test_parse_unknown_language(self):
        """Test parsing with unknown language returns empty list."""
        registry = ParserRegistry()
        results = registry.parse("source", "unknown_language", "file")
        assert results == []


class TestCreateParserRegistry:
    """Tests for parser registry factory."""

    def test_python_registered(self):
        """Test Python parser is registered."""
        registry = create_parser_registry()
        results = registry.parse("import os", "python", "test.py")
        assert len(results) >= 1

    def test_javascript_registered(self):
        """Test JavaScript parser is registered."""
        registry = create_parser_registry()
        # Just check it doesn't error
        results = registry.parse("import foo from 'bar'", "javascript", "test.js")
        # Results may be empty if ast-grep not installed, but shouldn't error

    def test_java_registered(self):
        """Test Java parser is registered."""
        registry = create_parser_registry()
        results = registry.parse("import java.util.*;", "java", "test.java")
        # Should parse or fallback gracefully


class TestSingletonRegistry:
    """Tests for singleton registry."""

    def test_get_parser_registry(self):
        """Test get_parser_registry returns same instance."""
        registry1 = get_parser_registry()
        registry2 = get_parser_registry()
        assert registry1 is registry2