"""Universal parser registry and language-specific parsers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ImportInfo:
    """Parsed import information."""

    module: str  # Target module/package name
    name: Optional[str]  # Imported name (for "from import" case)
    kind: str  # import, from, require, table, procedure, etc.
    line: int  # Line number
    is_external: bool  # Is external dependency
    raw: str  # Original statement (for debugging)


class ParserRegistry:
    """Registry for language-specific parsers."""

    def __init__(self):
        self._parsers: dict[str, callable] = {}
        self._resolve_funcs: dict[str, callable] = {}

    def register(self, language: str, parser: callable) -> None:
        """Register a parser for a language.

        Args:
            language: Language identifier (e.g., 'python', 'java')
            parser: Function(source, filepath) -> list[ImportInfo]
        """
        self._parsers[language] = parser

    def register_resolver(self, language: str, resolver: callable) -> None:
        """Register a resolver for a language.

        Args:
            language: Language identifier
            resolver: Function(module, source_file, known_paths) -> str|None
        """
        self._resolve_funcs[language] = resolver

    def parse(self, source: str, language: str, filepath: str) -> list[ImportInfo]:
        """Parse imports from source code.

        Args:
            source: Source code content
            language: Programming language
            filepath: File path (for context)

        Returns:
            List of ImportInfo
        """
        parser = self._parsers.get(language)
        if parser:
            return parser(source, filepath)
        return []

    def resolve(
        self, module: str, source_file: str, language: str, known_paths: set[str]
    ) -> Optional[str]:
        """Resolve module to file path.

        Args:
            module: Module/package name
            source_file: Source file path
            language: Programming language
            known_paths: Set of known file paths

        Returns:
            Resolved file path or None
        """
        resolver = self._resolve_funcs.get(language)
        if resolver:
            return resolver(module, source_file, known_paths)
        return None


# ========== Python Parser (using stdlib ast) ==========


def parse_python(source: str, filepath: str) -> list[ImportInfo]:
    """Parse Python imports using stdlib ast module.

    Args:
        source: Python source code
        filepath: File path (unused, for interface consistency)

    Returns:
        List of ImportInfo
    """
    import ast

    results = []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.append(
                    ImportInfo(
                        module=alias.name,
                        name=None,
                        kind="import",
                        line=node.lineno or 0,
                        is_external=not alias.name.startswith("."),
                        raw=ast.unparse(node),
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = node.level  # 0=absolute, 1+=relative

            for alias in node.names:
                full_module = (
                    f"{'.' * level}{module}" if level > 0 or module else module
                )
                is_external = level == 0 and not module.startswith(".")
                results.append(
                    ImportInfo(
                        module=full_module,
                        name=alias.name,
                        kind="from",
                        line=node.lineno or 0,
                        is_external=is_external,
                        raw=ast.unparse(node),
                    )
                )

    return results


def resolve_python(
    module: str, source_file: str, known_paths: set[str]
) -> Optional[str]:
    """Resolve Python module to file path.

    Args:
        module: Module name (e.g., 'os.path', 'collections')
        source_file: Source file path
        known_paths: Set of known file paths

    Returns:
        Resolved file path or None
    """
    rel = module.replace(".", "/")
    candidates = [
        f"{rel}.py",
        f"{rel}/__init__.py",
        f"src/{rel}.py",
        f"src/{rel}/__init__.py",
    ]
    for c in candidates:
        if c in known_paths:
            return c
    return None


# ========== JavaScript/TypeScript Parser (using ast-grep) ==========


def _parse_js_with_astgrep(source: str, language: str) -> list[ImportInfo]:
    """Parse JS/TS imports using ast-grep.

    Args:
        source: Source code
        language: 'javascript' or 'typescript'

    Returns:
        List of ImportInfo
    """
    results = []

    try:
        from ast_grep_py import SgRoot
    except ImportError:
        return _parse_js_regex(source, "")

    sg = SgRoot(source, language)
    root = sg.root()

    # import x from 'y'
    for imp in root.find_all(pattern="import $NAME from $SOURCE"):
        name = imp.get_match("NAME")
        source_match = imp.get_match("SOURCE")
        if name and source_match:
            results.append(
                ImportInfo(
                    module=source_match.text().strip("'\""),
                    name=name.text(),
                    kind="import",
                    line=imp.range().start.line + 1,
                    is_external=True,
                    raw=imp.text(),
                )
            )

    # import 'x' (side effect only)
    for imp in root.find_all(pattern="import $SOURCE"):
        source_match = imp.get_match("SOURCE")
        if source_match and not name:
            text = source_match.text().strip("'\"")
            results.append(
                ImportInfo(
                    module=text,
                    name=None,
                    kind="import",
                    line=imp.range().start.line + 1,
                    is_external=True,
                    raw=imp.text(),
                )
            )

    # require('x')
    for req in root.find_all(pattern="require($SOURCE)"):
        source_text = req.text()
        if source_text:
            # Extract the argument from require(xxx)
            match = re.search(r"require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", source_text)
            if match:
                results.append(
                    ImportInfo(
                        module=match.group(1),
                        name=None,
                        kind="require",
                        line=req.range().start.line + 1,
                        is_external=True,
                        raw=req.text(),
                    )
                )

    return results


def _parse_js_regex(source: str, filepath: str) -> list[ImportInfo]:
    """Fallback regex parser for JavaScript.

    Args:
        source: Source code
        filepath: File path (unused)

    Returns:
        List of ImportInfo
    """
    results = []
    lines = source.split("\n")

    # Remove comments first
    filtered_lines = []
    in_block_comment = False
    for line in lines:
        if "/*" in line:
            in_block_comment = True
        if "*/" in line:
            in_block_comment = False
            continue
        if in_block_comment:
            continue
        if "//" in line:
            line = line[: line.index("//")]
        filtered_lines.append(line)

    content = "\n".join(filtered_lines)

    # import x from 'y'
    for match in re.finditer(
        r"""import\s+(?:(?:type\s+)?(?:{$NAME}\s+from\s+)?|(?:default\s+)?(?:{$NAME}\s+from\s+)?)['"]([^'"]+)['"]""",
        content,
        re.MULTILINE,
    ):
        results.append(
            ImportInfo(
                module=match.group(1),
                name=None,
                kind="import",
                line=content[: match.start()].count("\n") + 1,
                is_external=True,
                raw=match.group(0),
            )
        )

    # require('x')
    for match in re.finditer(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""", content):
        results.append(
            ImportInfo(
                module=match.group(1),
                name=None,
                kind="require",
                line=content[: match.start()].count("\n") + 1,
                is_external=True,
                raw=match.group(0),
            )
        )

    return results


def parse_javascript(source: str, filepath: str) -> list[ImportInfo]:
    """Parse JavaScript imports.

    Args:
        source: Source code
        filepath: File path

    Returns:
        List of ImportInfo
    """
    return _parse_js_with_astgrep(source, "javascript")


def parse_typescript(source: str, filepath: str) -> list[ImportInfo]:
    """Parse TypeScript imports.

    Args:
        source: Source code
        filepath: File path

    Returns:
        List of ImportInfo
    """
    return _parse_js_with_astgrep(source, "typescript")


def resolve_js(
    module: str, source_file: str, known_paths: set[str]
) -> Optional[str]:
    """Resolve JavaScript/TypeScript module to file path.

    Args:
        module: Module name
        source_file: Source file path
        known_paths: Set of known file paths

    Returns:
        Resolved file path or None
    """
    if module.startswith("."):
        base_dir = str(Path(source_file).parent)
        rel = str(Path(base_dir) / module)
    else:
        rel = module

    candidates = [
        rel,
        f"{rel}.ts",
        f"{rel}.tsx",
        f"{rel}.js",
        f"{rel}.jsx",
        f"{rel}/index.ts",
        f"{rel}/index.tsx",
        f"{rel}/index.js",
    ]

    for c in candidates:
        if c in known_paths:
            return c
    return None


# ========== Java Parser (using tree-sitter) ==========


def parse_java(source: str, filepath: str) -> list[ImportInfo]:
    """Parse Java imports using tree-sitter-java.

    Args:
        source: Java source code
        filepath: File path (unused)

    Returns:
        List of ImportInfo
    """
    results = []

    try:
        import tree_sitter_java as tsjava
        from tree_sitter import Language, Parser, Query
    except ImportError:
        return _parse_java_regex(source, filepath)

    JAVA_LANGUAGE = Language(tsjava.language())
    parser = Parser(JAVA_LANGUAGE)
    tree = parser.parse(bytes(source, "utf8"))

    # Query for import declarations
    QUERY = """
    (import_declaration
      (scoped_identifier) @module)

    (import_declaration
      (identifier) @module)

    (import_declaration
      (scoped_identifier
        (identifier) @module
        "*") @wildcard)
    """

    query = Query(JAVA_LANGUAGE, QUERY)

    for node, capture_name in query.captures(tree.root_node):
        module_text = source[node.start_byte : node.end_byte]
        is_wildcard = capture_name == "wildcard"
        is_static = False  # Could check for static keyword in future

        results.append(
            ImportInfo(
                module=module_text.rstrip(".*"),
                name=None,
                kind="wildcard" if is_wildcard else "import",
                line=node.start_point[0] + 1,
                is_external=True,
                raw=module_text,
            )
        )

    return results


def _parse_java_regex(source: str, filepath: str) -> list[ImportInfo]:
    """Fallback regex parser for Java.

    Args:
        source: Source code
        filepath: File path (unused)

    Returns:
        List of ImportInfo
    """
    results = []
    lines = source.split("\n")

    in_block_comment = False
    for i, line in enumerate(lines, 1):
        if "/*" in line:
            in_block_comment = True
        if "*/" in line:
            in_block_comment = False
            continue
        if in_block_comment:
            continue

        if "//" in line:
            line = line[: line.index("//")]

        match = re.match(r"^\s*import\s+(static\s+)?([\w.]+)(\.\*)?\s*;", line.strip())
        if match:
            results.append(
                ImportInfo(
                    module=match.group(2),
                    name=None,
                    kind="static" if match.group(1) else "import",
                    line=i,
                    is_external=True,
                    raw=line.strip(),
                )
            )

    return results


def resolve_java(
    module: str, source_file: str, known_paths: set[str]
) -> Optional[str]:
    """Resolve Java module to file path.

    Args:
        module: Module name (e.g., 'java.util.List')
        source_file: Source file path
        known_paths: Set of known file paths

    Returns:
        Resolved file path or None
    """
    rel = module.replace(".", "/")
    candidates = [f"src/main/java/{rel}.java", f"{rel}.java"]

    for c in candidates:
        if c in known_paths:
            return c
    return None


# ========== Go Parser ==========


def parse_go(source: str, filepath: str) -> list[ImportInfo]:
    """Parse Go imports.

    Args:
        source: Go source code
        filepath: File path (unused)

    Returns:
        List of ImportInfo
    """
    results = []

    try:
        import goast
    except ImportError:
        return _parse_go_regex(source, filepath)

    try:
        fset = goast.NewFileSet()
        file, _ = goast.ParseFile(fset, filepath, source, goast.ImportsOnly)
        if file != None:
            for _, imp in file.Imports:
                if imp != None:
                    path = imp.Path.Value[1 : len(imp.Path.Value) - 1]  # Remove quotes
                    results.append(
                        ImportInfo(
                            module=path,
                            name=None,
                            kind="import",
                            line=fset.Position(imp.Pos()).Line,
                            is_external=True,
                            raw=path,
                        )
                    )
    except Exception:
        return _parse_go_regex(source, filepath)

    return results


def _parse_go_regex(source: str, filepath: str) -> list[ImportInfo]:
    """Fallback regex parser for Go.

    Args:
        source: Source code
        filepath: File path (unused)

    Returns:
        List of ImportInfo
    """
    results = []

    # Match import "package" statements
    for match in re.finditer(r'import\s+"([^"]+)"', source):
        results.append(
            ImportInfo(
                module=match.group(1),
                name=None,
                kind="import",
                line=source[: match.start()].count("\n") + 1,
                is_external=True,
                raw=match.group(0),
            )
        )

    # Match import ( "package" ) blocks
    block_match = re.search(r"import\s*\(([\s\S]*?)\)", source)
    if block_match:
        block_content = block_match.group(1)
        for match in re.finditer(r'"([^"]+)"', block_content):
            results.append(
                ImportInfo(
                    module=match.group(1),
                    name=None,
                    kind="import",
                    line=source[: match.start()].count("\n") + 1,
                    is_external=True,
                    raw=match.group(0),
                )
            )

    return results


def resolve_go(
    module: str, source_file: str, known_paths: set[str]
) -> Optional[str]:
    """Resolve Go module to file path.

    Args:
        module: Module name (e.g., 'fmt', 'net/http')
        source_file: Source file path
        known_paths: Set of known file paths

    Returns:
        Resolved file path or None
    """
    parts = module.split("/")
    if len(parts) >= 2:
        candidates = [f"{'/'.join(parts[-2:])}.go"]
    else:
        candidates = [f"{module}.go"]

    for c in candidates:
        if c in known_paths:
            return c
    return None


# ========== Rust Parser ==========


def parse_rust(source: str, filepath: str) -> list[ImportInfo]:
    """Parse Rust imports.

    Args:
        source: Rust source code
        filepath: File path (unused)

    Returns:
        List of ImportInfo
    """
    results = []
    lines = source.split("\n")

    for i, line in enumerate(lines, 1):
        # Skip comments
        if line.strip().startswith("//"):
            continue
        if "//" in line:
            line = line[: line.index("//")]

        # use foo::bar;
        match = re.match(r"^\s*use\s+([\w:]+)", line.strip())
        if match:
            module = match.group(1)
            results.append(
                ImportInfo(
                    module=module,
                    name=None,
                    kind="import",
                    line=i,
                    is_external=not module.startswith("crate")
                    and not module.startswith("super")
                    and not module.startswith("self"),
                    raw=line.strip(),
                )
            )

        # mod foo;
        mod_match = re.match(r"^\s*mod\s+(\w+)", line.strip())
        if mod_match:
            module = mod_match.group(1)
            results.append(
                ImportInfo(
                    module=module,
                    name=None,
                    kind="mod",
                    line=i,
                    is_external=False,
                    raw=line.strip(),
                )
            )

    return results


def resolve_rust(
    module: str, source_file: str, known_paths: set[str]
) -> Optional[str]:
    """Resolve Rust module to file path.

    Args:
        module: Module name
        source_file: Source file path
        known_paths: Set of known file paths

    Returns:
        Resolved file path or None
    """
    rel = module.split("::")[0].replace("::", "/")
    candidates = [
        f"src/{rel}.rs",
        f"src/{rel}/mod.rs",
        f"{rel}.rs",
    ]

    for c in candidates:
        if c in known_paths:
            return c
    return None


# ========== SQL Parser (enhanced regex) ==========


def parse_sql(source: str, filepath: str) -> list[ImportInfo]:
    """Parse SQL dependencies.

    Args:
        source: SQL source code
        filepath: File path (unused)

    Returns:
        List of ImportInfo
    """
    results = []

    # Remove comments
    lines = source.split("\n")
    filtered_lines = []
    in_block_comment = False
    for line in lines:
        if "/*" in line:
            in_block_comment = True
        if "*/" in line:
            in_block_comment = False
            continue
        if in_block_comment:
            continue
        if line.strip().startswith("--"):
            continue
        filtered_lines.append(line)

    content = "\n".join(filtered_lines)

    # PostgreSQL include: \i other.sql
    for match in re.finditer(r"\\i\s+['\"]?([^'\"\s]+)['\"]?", content):
        results.append(
            ImportInfo(
                module=match.group(1),
                name=None,
                kind="sql_file",
                line=content[: match.start()].count("\n") + 1,
                is_external=False,
                raw=match.group(0),
            )
        )

    # Table references: SELECT, INSERT, UPDATE, DELETE, CREATE
    table_patterns = [
        r"(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(\w+)",
        r"FROM\s+(\w+)",
        r"JOIN\s+(\w+)",
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
        r"ALTER\s+TABLE\s+(\w+)",
        r"DROP\s+TABLE\s+(\w+)",
    ]

    for pattern in table_patterns:
        for match in re.finditer(pattern, content, re.IGNORECASE):
            table = match.group(1)
            if table.upper() not in (
                "FROM",
                "INTO",
                "UPDATE",
                "DELETE",
                "SELECT",
                "INSERT",
                "JOIN",
                "TABLE",
                "ALTER",
                "DROP",
            ):
                line = content[: match.start()].count("\n") + 1
                results.append(
                    ImportInfo(
                        module=table,
                        name=None,
                        kind="table",
                        line=line,
                        is_external=True,
                        raw=match.group(0),
                    )
                )

    # Stored procedure/function calls: CALL, EXEC, EXECUTE
    for match in re.finditer(
        r"(?:CALL|EXEC|EXECUTE)\s+(\w+)", content, re.IGNORECASE
    ):
        results.append(
            ImportInfo(
                module=match.group(1),
                name=None,
                kind="procedure",
                line=content[: match.start()].count("\n") + 1,
                is_external=False,
                raw=match.group(0),
            )
        )

    # Function calls with schema: schema.function
    for match in re.finditer(r"(\w+)\.(\w+)\s*\(", content):
        # Could be a function call - only add if it looks like one
        schema, func = match.group(1), match.group(2)
        if func.upper() not in ("SELECT", "FROM", "INSERT", "UPDATE", "DELETE"):
            results.append(
                ImportInfo(
                    module=f"{schema}.{func}",
                    name=None,
                    kind="function",
                    line=content[: match.start()].count("\n") + 1,
                    is_external=True,
                    raw=match.group(0),
                )
            )

    return results


def resolve_sql(
    module: str, source_file: str, known_paths: set[str]
) -> Optional[str]:
    """Resolve SQL object to file path.

    Args:
        module: SQL object name
        source_file: Source file path
        known_paths: Set of known file paths

    Returns:
        Resolved file path (same module assumed) or None
    """
    # SQL tables/procedures don't map directly to files
    # Check if there's a matching .sql file
    if module in known_paths:
        return module
    if f"{module}.sql" in known_paths:
        return f"{module}.sql"
    return None


# ========== Default fallback parser ==========


def _parse_default(source: str, filepath: str) -> list[ImportInfo]:
    """Default parser for unknown languages.

    Args:
        source: Source code
        filepath: File path

    Returns:
        Empty list
    """
    return []


def resolve_default(
    module: str, source_file: str, known_paths: set[str]
) -> Optional[str]:
    """Default resolver for unknown languages.

    Args:
        module: Module name
        source_file: Source file path
        known_paths: Set of known file paths

    Returns:
        None
    """
    return None


# ========== Parser Registry Factory ==========


def create_parser_registry() -> ParserRegistry:
    """Create and configure the parser registry.

    Returns:
        Configured ParserRegistry instance
    """
    registry = ParserRegistry()

    # Python
    registry.register("python", parse_python)
    registry.register("pyi", parse_python)
    registry.register_resolver("python", resolve_python)
    registry.register_resolver("pyi", resolve_python)

    # JavaScript/TypeScript
    registry.register("javascript", parse_javascript)
    registry.register("jsx", parse_javascript)
    registry.register("typescript", parse_typescript)
    registry.register("tsx", parse_typescript)
    registry.register("mjs", parse_javascript)
    registry.register("cjs", parse_javascript)
    registry.register_resolver("javascript", resolve_js)
    registry.register_resolver("jsx", resolve_js)
    registry.register_resolver("typescript", resolve_js)
    registry.register_resolver("tsx", resolve_js)
    registry.register_resolver("mjs", resolve_js)
    registry.register_resolver("cjs", resolve_js)

    # Java
    registry.register("java", parse_java)
    registry.register_resolver("java", resolve_java)

    # Go
    registry.register("go", parse_go)
    registry.register_resolver("go", resolve_go)

    # Rust
    registry.register("rust", parse_rust)
    registry.register_resolver("rust", resolve_rust)

    # SQL
    registry.register("sql", parse_sql)
    registry.register_resolver("sql", resolve_sql)

    # C/C++
    registry.register("c", _parse_default)
    registry.register("cpp", _parse_default)

    # Ruby, PHP, Swift, Kotlin, etc.
    for lang in [
        "ruby",
        "php",
        "swift",
        "kotlin",
        "scala",
        "csharp",
        "dart",
        "lua",
        "haskell",
    ]:
        registry.register(lang, _parse_default)
        registry.register_resolver(lang, resolve_default)

    return registry


# Singleton instance
_default_registry: Optional[ParserRegistry] = None


def get_parser_registry() -> ParserRegistry:
    """Get the default parser registry singleton.

    Returns:
        ParserRegistry instance
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = create_parser_registry()
    return _default_registry


def parse_imports(source: str, language: str, filepath: str) -> list[ImportInfo]:
    """Convenience function to parse imports.

    Args:
        source: Source code
        language: Programming language
        filepath: File path

    Returns:
        List of ImportInfo
    """
    return get_parser_registry().parse(source, language, filepath)


def resolve_import(
    module: str, source_file: str, language: str, known_paths: set[str]
) -> Optional[str]:
    """Convenience function to resolve imports.

    Args:
        module: Module name
        source_file: Source file path
        language: Programming language
        known_paths: Set of known file paths

    Returns:
        Resolved file path or None
    """
    return get_parser_registry().resolve(module, source_file, language, known_paths)


# ========== Symbol Registry (Symbol-level parsing) ==========


from repowiki.core.symbols import SymbolNode, SymbolKind


class SymbolRegistry:
    """Registry for language-specific symbol parsers."""

    def __init__(self):
        self._parsers: dict[str, callable] = {}

    def register(self, language: str, parser: callable) -> None:
        """Register a symbol parser for a language.

        Args:
            language: Language identifier (e.g., 'python', 'java')
            parser: Function(source, filepath) -> list[SymbolNode]
        """
        self._parsers[language] = parser

    def parse_symbols(self, source: str, language: str, filepath: str) -> list[SymbolNode]:
        """Parse symbols from source code.

        Args:
            source: Source code content
            language: Programming language
            filepath: File path (for context)

        Returns:
            List of SymbolNode
        """
        parser = self._parsers.get(language)
        if parser:
            return parser(source, filepath)
        return []


# ========== Python Symbol Parser ==========


def parse_python_symbols(source: str, filepath: str) -> list[SymbolNode]:
    """Parse Python symbols (functions, classes, variables) from source.

    Args:
        source: Python source code
        filepath: File path (for symbol ID generation)

    Returns:
        List of SymbolNode
    """
    import ast

    symbols = []

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(_create_python_function_symbol(node, filepath))
        elif isinstance(node, ast.ClassDef):
            symbols.append(_create_python_class_symbol(node, filepath))
        elif isinstance(node, ast.Assign):
            # Variable assignments at module/class level
            for target in node.targets:
                if isinstance(target, ast.Name):
                    symbols.append(_create_python_variable_symbol(target, node, filepath))

    return symbols


def _create_python_function_symbol(node: ast.FunctionDef | ast.AsyncFunctionDef, filepath: str) -> SymbolNode:
    """Create a SymbolNode for a Python function."""
    # Build signature
    args = node.args
    params = []

    # Positional-only args
    for arg in args.posonlyargs:
        params.append(arg.arg)

    # Regular args
    for arg in args.args:
        params.append(arg.arg)

    # *args
    if args.vararg:
        params.append(f"*{args.vararg.arg}")

    # Keyword-only args
    for arg in args.kwonlyargs:
        params.append(f"{arg.arg}=")

    # **kwargs
    if args.kwarg:
        params.append(f"**{args.kwarg.arg}")

    # Return annotation
    return_annotation = ""
    if node.returns:
        return_annotation = f" -> {ast.unparse(node.returns)}"

    signature = f"def {node.name}({', '.join(params)}){return_annotation}"

    # Get docstring
    doc = ast.get_docstring(node) or ""

    return SymbolNode(
        id=f"{filepath}:{node.name}:{node.lineno}",
        name=node.name,
        kind=SymbolKind.FUNCTION,
        file=filepath,
        line=node.lineno,
        end_line=node.end_lineno or node.lineno,
        signature=signature,
        doc=doc,
    )


def _create_python_class_symbol(node: ast.ClassDef, filepath: str) -> SymbolNode:
    """Create a SymbolNode for a Python class."""
    doc = ast.get_docstring(node) or ""

    # Get base classes
    bases = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            bases.append(base.id)
        elif isinstance(base, ast.Attribute):
            bases.append(ast.unparse(base))

    signature = f"class {node.name}"
    if bases:
        signature += f"({', '.join(bases)})"

    return SymbolNode(
        id=f"{filepath}:{node.name}:{node.lineno}",
        name=node.name,
        kind=SymbolKind.CLASS,
        file=filepath,
        line=node.lineno,
        end_line=node.end_lineno or node.lineno,
        signature=signature,
        doc=doc,
    )


def _create_python_variable_symbol(target: ast.Name, node: ast.Assign, filepath: str) -> SymbolNode:
    """Create a SymbolNode for a Python variable."""
    return SymbolNode(
        id=f"{filepath}:{target.id}:{node.lineno}",
        name=target.id,
        kind=SymbolKind.VARIABLE,
        file=filepath,
        line=node.lineno,
        end_line=node.end_lineno or node.lineno,
        signature="",
        doc="",
    )


# ========== JavaScript/TypeScript Symbol Parser ==========


def parse_js_symbols(source: str, filepath: str) -> list[SymbolNode]:
    """Parse JavaScript/TypeScript symbols using ast-grep.

    Args:
        source: JavaScript/TypeScript source code
        filepath: File path

    Returns:
        List of SymbolNode
    """
    try:
        from ast_grep_py import SgRoot
    except ImportError:
        return _parse_js_symbols_regex(source, filepath)

    symbols = []
    sg = SgRoot(source, "javascript")
    root = sg.root()

    # Parse function declarations: function name(...) {...}
    for fn in root.find_all(pattern="function $NAME($$$ARGS) { $$$BODY }"):
        name_match = fn.get_match("NAME")
        if name_match:
            symbols.append(SymbolNode(
                id=f"{filepath}:{name_match.text()}:{fn.range().start.line + 1}",
                name=name_match.text(),
                kind=SymbolKind.FUNCTION,
                file=filepath,
                line=fn.range().start.line + 1,
                end_line=fn.range().end.line + 1,
                signature=f"function {name_match.text()}(...)",
                doc="",
            ))

    # Parse const/let/var declarations: const name = ...
    for decl in root.find_all(pattern="const $NAME = $VALUE"):
        name_match = decl.get_match("NAME")
        if name_match:
            symbols.append(SymbolNode(
                id=f"{filepath}:{name_match.text()}:{decl.range().start.line + 1}",
                name=name_match.text(),
                kind=SymbolKind.VARIABLE,
                file=filepath,
                line=decl.range().start.line + 1,
                end_line=decl.range().end.line + 1,
                signature="",
                doc="",
            ))

    # Parse class declarations: class Name {...}
    for cls in root.find_all(pattern="class $NAME { $$$BODY }"):
        name_match = cls.get_match("NAME")
        if name_match:
            symbols.append(SymbolNode(
                id=f"{filepath}:{name_match.text()}:{cls.range().start.line + 1}",
                name=name_match.text(),
                kind=SymbolKind.CLASS,
                file=filepath,
                line=cls.range().start.line + 1,
                end_line=cls.range().end.line + 1,
                signature=f"class {name_match.text()}",
                doc="",
            ))

    return symbols


def _parse_js_symbols_regex(source: str, filepath: str) -> list[SymbolNode]:
    """Fallback regex parser for JavaScript symbols."""
    import re

    symbols = []

    # Remove comments
    filtered_lines = []
    in_block_comment = False
    for line in source.split("\n"):
        if "/*" in line:
            in_block_comment = True
        if "*/" in line:
            in_block_comment = False
            continue
        if in_block_comment:
            continue
        if "//" in line:
            line = line[:line.index("//")]
        filtered_lines.append(line)

    content = "\n".join(filtered_lines)

    # function name(...) {...}
    for match in re.finditer(r"function\s+(\w+)\s*\([^)]*\)", content):
        name = match.group(1)
        line_num = content[:match.start()].count("\n") + 1
        symbols.append(SymbolNode(
            id=f"{filepath}:{name}:{line_num}",
            name=name,
            kind=SymbolKind.FUNCTION,
            file=filepath,
            line=line_num,
            end_line=line_num,
            signature=f"function {name}(...)",
            doc="",
        ))

    # const/let/var name = ...
    for match in re.finditer(r"(?:const|let|var)\s+(\w+)\s*=", content):
        name = match.group(1)
        line_num = content[:match.start()].count("\n") + 1
        symbols.append(SymbolNode(
            id=f"{filepath}:{name}:{line_num}",
            name=name,
            kind=SymbolKind.VARIABLE,
            file=filepath,
            line=line_num,
            end_line=line_num,
            signature="",
            doc="",
        ))

    # class Name {...}
    for match in re.finditer(r"class\s+(\w+)\s*\{", content):
        name = match.group(1)
        line_num = content[:match.start()].count("\n") + 1
        symbols.append(SymbolNode(
            id=f"{filepath}:{name}:{line_num}",
            name=name,
            kind=SymbolKind.CLASS,
            file=filepath,
            line=line_num,
            end_line=line_num,
            signature=f"class {name}",
            doc="",
        ))

    return symbols


def parse_typescript_symbols(source: str, filepath: str) -> list[SymbolNode]:
    """Parse TypeScript symbols (same as JavaScript for now)."""
    return parse_js_symbols(source, filepath)


# ========== Java Symbol Parser ==========


def parse_java_symbols(source: str, filepath: str) -> list[SymbolNode]:
    """Parse Java symbols using tree-sitter.

    Args:
        source: Java source code
        filepath: File path

    Returns:
        List of SymbolNode
    """
    try:
        import tree_sitter_java as tsjava
        from tree_sitter import Language, Parser, Query
    except ImportError:
        return _parse_java_symbols_regex(source, filepath)

    symbols = []

    try:
        JAVA_LANGUAGE = Language(tsjava.language())
        parser = Parser(JAVA_LANGUAGE)
        tree = parser.parse(bytes(source, "utf8"))

        # Query for method declarations
        METHOD_QUERY = """
        (method_declaration
          (identifier) @method_name
          (modifiers)
          (type)? @return_type
          (formal_parameters) @params)
        """
        query = Query(JAVA_LANGUAGE, METHOD_QUERY)
        for node, capture_name in query.captures(tree.root_node):
            if capture_name == "method_name":
                method_name = source[node.start_byte:node.end_byte]
                line_num = node.start_point[0] + 1
                symbols.append(SymbolNode(
                    id=f"{filepath}:{method_name}:{line_num}",
                    name=method_name,
                    kind=SymbolKind.METHOD,
                    file=filepath,
                    line=line_num,
                    end_line=line_num,
                    signature=f"{method_name}(...)",
                    doc="",
                ))

        # Query for class declarations
        CLASS_QUERY = """
        (class_declaration
          (identifier) @class_name
          (superclass)? @superclass
          (interfaces)? @interfaces)
        """
        class_query = Query(JAVA_LANGUAGE, CLASS_QUERY)
        for node, capture_name in class_query.captures(tree.root_node):
            if capture_name == "class_name":
                class_name = source[node.start_byte:node.end_byte]
                line_num = node.start_point[0] + 1
                symbols.append(SymbolNode(
                    id=f"{filepath}:{class_name}:{line_num}",
                    name=class_name,
                    kind=SymbolKind.CLASS,
                    file=filepath,
                    line=line_num,
                    end_line=line_num,
                    signature=f"class {class_name}",
                    doc="",
                ))

    except Exception:
        return _parse_java_symbols_regex(source, filepath)

    return symbols


def _parse_java_symbols_regex(source: str, filepath: str) -> list[SymbolNode]:
    """Fallback regex parser for Java symbols."""
    import re

    symbols = []

    lines = source.split("\n")

    for i, line in enumerate(lines, 1):
        # Skip comments
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if "//" in line:
            line = line[:line.index("//")]

        # public/private/protected class Name {...}
        class_match = re.match(r"(?:public|private|protected)?\s*(?:abstract|final)?\s*class\s+(\w+)", line)
        if class_match:
            class_name = class_match.group(1)
            symbols.append(SymbolNode(
                id=f"{filepath}:{class_name}:{i}",
                name=class_name,
                kind=SymbolKind.CLASS,
                file=filepath,
                line=i,
                end_line=i,
                signature=f"class {class_name}",
                doc="",
            ))

        # public/private/protected return_type method_name(...) {...}
        method_match = re.match(
            r"(?:public|private|protected)?\s*(?:static)?\s*(?:final)?\s*(\w+)\s+(\w+)\s*\(",
            line
        )
        if method_match:
            return_type = method_match.group(1)
            method_name = method_match.group(2)
            # Skip constructors and common keywords
            if method_name not in ("if", "while", "for", "switch", "class", "interface"):
                symbols.append(SymbolNode(
                    id=f"{filepath}:{method_name}:{i}",
                    name=method_name,
                    kind=SymbolKind.METHOD,
                    file=filepath,
                    line=i,
                    end_line=i,
                    signature=f"{method_name}(...)",
                    doc="",
                ))

    return symbols


# ========== Go Symbol Parser ==========


def parse_go_symbols(source: str, filepath: str) -> list[SymbolNode]:
    """Parse Go symbols.

    Args:
        source: Go source code
        filepath: File path

    Returns:
        List of SymbolNode
    """
    # Note: goast is a Go library accessed via cgo, not Python.
    # The goast import may work if properly installed, but the API is Go-style.
    # For safety, we fall back to regex parsing.
    return _parse_go_symbols_regex(source, filepath)


def _parse_go_symbols_regex(source: str, filepath: str) -> list[SymbolNode]:
    """Fallback regex parser for Go symbols."""
    import re

    symbols = []

    lines = source.split("\n")

    for i, line in enumerate(lines, 1):
        # Skip comments
        if line.strip().startswith("//"):
            continue

        # func name(...) {...}
        func_match = re.match(r"func\s+(\w+)\s*\(", line)
        if func_match:
            func_name = func_match.group(1)
            symbols.append(SymbolNode(
                id=f"{filepath}:{func_name}:{i}",
                name=func_name,
                kind=SymbolKind.FUNCTION,
                file=filepath,
                line=i,
                end_line=i,
                signature=f"func {func_name}(...)",
                doc="",
            ))

        # type Name struct {...}
        type_match = re.match(r"type\s+(\w+)\s+(struct|interface)", line)
        if type_match:
            type_name = type_match.group(1)
            kind = SymbolKind.INTERFACE if type_match.group(2) == "interface" else SymbolKind.CLASS
            symbols.append(SymbolNode(
                id=f"{filepath}:{type_name}:{i}",
                name=type_name,
                kind=kind,
                file=filepath,
                line=i,
                end_line=i,
                signature=f"type {type_name}",
                doc="",
            ))

    return symbols


# ========== Rust Symbol Parser ==========


def parse_rust_symbols(source: str, filepath: str) -> list[SymbolNode]:
    """Parse Rust symbols using regex.

    Args:
        source: Rust source code
        filepath: File path

    Returns:
        List of SymbolNode
    """
    import re

    symbols = []

    lines = source.split("\n")

    for i, line in enumerate(lines, 1):
        # Skip comments
        if line.strip().startswith("//"):
            continue

        # fn name(...) -> ... {...}
        fn_match = re.match(r"fn\s+(\w+)\s*\(", line)
        if fn_match:
            fn_name = fn_match.group(1)
            symbols.append(SymbolNode(
                id=f"{filepath}:{fn_name}:{i}",
                name=fn_name,
                kind=SymbolKind.FUNCTION,
                file=filepath,
                line=i,
                end_line=i,
                signature=f"fn {fn_name}(...)",
                doc="",
            ))

        # struct Name {...}
        struct_match = re.match(r"struct\s+(\w+)", line)
        if struct_match:
            struct_name = struct_match.group(1)
            symbols.append(SymbolNode(
                id=f"{filepath}:{struct_name}:{i}",
                name=struct_name,
                kind=SymbolKind.CLASS,
                file=filepath,
                line=i,
                end_line=i,
                signature=f"struct {struct_name}",
                doc="",
            ))

        # enum Name {...}
        enum_match = re.match(r"enum\s+(\w+)", line)
        if enum_match:
            enum_name = enum_match.group(1)
            symbols.append(SymbolNode(
                id=f"{filepath}:{enum_name}:{i}",
                name=enum_name,
                kind=SymbolKind.CLASS,  # Enum as class-like
                file=filepath,
                line=i,
                end_line=i,
                signature=f"enum {enum_name}",
                doc="",
            ))

        # impl Name {...}
        impl_match = re.match(r"impl\s+(?:<[^>]+>)?\s*(\w+)", line)
        if impl_match:
            impl_name = impl_match.group(1)
            symbols.append(SymbolNode(
                id=f"{filepath}:{impl_name}:{i}",
                name=f"impl_{impl_name}",
                kind=SymbolKind.CLASS,  # Impl as class-like
                file=filepath,
                line=i,
                end_line=i,
                signature=f"impl {impl_name}",
                doc="",
            ))

    return symbols


# ========== Symbol Registry Factory ==========


# Singleton instance
_symbol_registry: Optional[SymbolRegistry] = None


def get_symbol_registry() -> SymbolRegistry:
    """Get the default symbol registry singleton.

    Returns:
        SymbolRegistry instance
    """
    global _symbol_registry
    if _symbol_registry is None:
        _symbol_registry = SymbolRegistry()

        # Register language parsers
        _symbol_registry.register("python", parse_python_symbols)
        _symbol_registry.register("pyi", parse_python_symbols)

        _symbol_registry.register("javascript", parse_js_symbols)
        _symbol_registry.register("jsx", parse_js_symbols)
        _symbol_registry.register("typescript", parse_typescript_symbols)
        _symbol_registry.register("tsx", parse_typescript_symbols)

        _symbol_registry.register("java", parse_java_symbols)
        _symbol_registry.register("go", parse_go_symbols)
        _symbol_registry.register("rust", parse_rust_symbols)

    return _symbol_registry


def parse_symbols(source: str, language: str, filepath: str) -> list[SymbolNode]:
    """Convenience function to parse symbols.

    Args:
        source: Source code
        language: Programming language
        filepath: File path

    Returns:
        List of SymbolNode
    """
    return get_symbol_registry().parse_symbols(source, language, filepath)