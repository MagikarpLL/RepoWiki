"""Architecture pattern recognition and knowledge extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import re


@dataclass
class ArchitecturePattern:
    """Detected architecture pattern."""

    name: str                           # Pattern name (e.g., "MVC", "Factory")
    confidence: float                   # Confidence score (0-1)
    participants: list[str] = field(default_factory=list)  # Symbol IDs
    description: str = ""               # Pattern description
    detected_keywords: list[str] = field(default_factory=list)  # Keywords that triggered detection


class ArchitectureRecognizer:
    """
    Recognizes architectural patterns from symbol names and relationships.

    Detects patterns like:
    - MVC (Model-View-Controller)
    - Factory
    - Observer
    - Singleton
    - Repository
    - Strategy
    """

    # Pattern definitions with keywords and weights
    PATTERN_DEFINITIONS = {
        "mvc": {
            "keywords": ["model", "view", "controller", "presenter"],
            "weight": 0.3,
            "description": "Model-View-Controller pattern",
        },
        "factory": {
            "keywords": ["factory", "builder", "create", "make"],
            "weight": 0.25,
            "description": "Factory/Builder pattern for object creation",
        },
        "observer": {
            "keywords": ["observer", "listener", "subscriber", "publisher", "event", "notification"],
            "weight": 0.3,
            "description": "Observer pattern for event handling",
        },
        "singleton": {
            "keywords": ["singleton", "getinstance", "_instance", "get_instance"],
            "weight": 0.2,
            "description": "Singleton pattern for single instance",
        },
        "repository": {
            "keywords": ["repository", "dao", "dataaccess", "mapper"],
            "weight": 0.25,
            "description": "Repository pattern for data access",
        },
        "strategy": {
            "keywords": ["strategy", "policy", "algorithm", "strategic"],
            "weight": 0.25,
            "description": "Strategy pattern for algorithms",
        },
        "adapter": {
            "keywords": ["adapter", "wrapper", "decorator", "bridge"],
            "weight": 0.25,
            "description": "Adapter pattern for interface compatibility",
        },
        "facade": {
            "keywords": ["facade", "service", "gateway", "mediator"],
            "weight": 0.25,
            "description": "Facade pattern for simplified interface",
        },
        "command": {
            "keywords": ["command", "action", "task", "job", "executor"],
            "weight": 0.25,
            "description": "Command pattern for request encapsulation",
        },
        "dependency_injection": {
            "keywords": ["injector", "container", "provider", "di"],
            "weight": 0.25,
            "description": "Dependency Injection pattern",
        },
    }

    def __init__(self):
        self._patterns: list[ArchitecturePattern] = []

    def recognize(self, symbols: list) -> list[ArchitecturePattern]:
        """
        Recognize architecture patterns from a list of symbols.

        Args:
            symbols: List of SymbolNode to analyze

        Returns:
            List of detected ArchitecturePattern
        """
        self._patterns = []
        symbol_names = {s.name.lower(): s.id for s in symbols}

        # Analyze each pattern type
        for pattern_name, config in self.PATTERN_DEFINITIONS.items():
            matched_symbols = []
            matched_keywords = []

            for keyword in config["keywords"]:
                for name, sid in symbol_names.items():
                    if keyword.lower() in name:
                        matched_symbols.append(sid)
                        matched_keywords.append(keyword)

            # Calculate confidence
            if len(matched_keywords) >= 2:
                confidence = min(
                    (len(matched_keywords) / len(config["keywords"])) + config["weight"],
                    1.0
                )

                pattern = ArchitecturePattern(
                    name=pattern_name.upper(),
                    confidence=confidence,
                    participants=list(set(matched_symbols)),
                    description=config["description"],
                    detected_keywords=list(set(matched_keywords)),
                )
                self._patterns.append(pattern)

        # Sort by confidence
        self._patterns.sort(key=lambda p: -p.confidence)

        return self._patterns

    def get_pattern_by_name(self, name: str) -> Optional[ArchitecturePattern]:
        """Get a detected pattern by name."""
        for p in self._patterns:
            if p.name == name.upper():
                return p
        return None

    def to_mermaid(self) -> str:
        """Generate Mermaid diagram of detected patterns."""
        if not self._patterns:
            return ""

        lines = ["graph TD"]

        for i, pattern in enumerate(self._patterns[:5]):  # Limit to 5 patterns
            safe_name = re.sub(r"[^a-zA-Z0-9]", "_", pattern.name)

            # Add pattern node
            lines.append(f"    P{i}[({pattern.name})]")
            lines.append(f"    P{i} ::: {safe_name}")

            # Add participant nodes
            for j, sid in enumerate(pattern.participants[:3]):  # Max 3 participants
                sym_name = sid.split(":")[-2] if ":" in sid else sid
                lines.append(f"    P{i}_{j}[({sym_name})]")
                lines.append(f"    P{i}_{j} --> P{i}")

        # Add style definitions
        lines.append("")
        lines.append("    classDef MVC fill:#f9f,stroke:#333,stroke-width:2px")
        lines.append("    classDef FACTORY fill:#9f9,stroke:#333,stroke-width:2px")
        lines.append("    classDef OBSERVER fill:#9ff,stroke:#333,stroke-width:2px")
        lines.append("    classDef SINGLETON fill:#ff9,stroke:#333,stroke-width:2px")
        lines.append("    classDef REPOSITORY fill:#f99,stroke:#333,stroke-width:2px")

        return "\n".join(lines)


class CallChainExtractor:
    """
    Extracts call chains between symbols from source code.

    Analyzes code to find:
    - Which symbols call which other symbols
    - Call frequency and depth
    - Potential circular dependencies
    """

    def __init__(self):
        self._call_edges: list[tuple[str, str, int]] = []  # (caller, callee, line)

    def extract_from_source(
        self,
        source: str,
        language: str,
        symbol_map: dict[str, str],  # name -> symbol_id
        file_path: str = ""
    ) -> list[tuple[str, str, int]]:
        """
        Extract call chains from source code.

        Args:
            source: Source code
            language: Programming language
            symbol_map: Map of symbol names to symbol IDs
            file_path: File path for context

        Returns:
            List of (caller_id, callee_id, line) tuples
        """
        self._call_edges = []

        if language == "python":
            self._extract_python_calls(source, symbol_map, file_path)
        elif language in ("javascript", "typescript"):
            self._extract_js_calls(source, symbol_map, file_path)
        elif language == "java":
            self._extract_java_calls(source, symbol_map, file_path)

        return self._call_edges

    def _extract_python_calls(self, source: str, symbol_map: dict, file_path: str) -> None:
        """Extract calls from Python source."""
        import ast

        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            return

        # Track current function/class context
        context_stack = []

        for node in ast.walk(tree):
            # Track function/class definitions
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                func_name = node.name
                func_id = symbol_map.get(func_name, f"{file_path}:{func_name}:{node.lineno}")
                context_stack.append(func_id)

            # Find calls
            if isinstance(node, ast.Call):
                callee_name = None

                if isinstance(node.func, ast.Name):
                    callee_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    # Handle obj.method() calls
                    callee_name = node.func.attr

                if callee_name and callee_name in symbol_map:
                    callee_id = symbol_map[callee_name]

                    # Record call from current context (or module level)
                    if context_stack:
                        caller_id = context_stack[-1]
                        self._call_edges.append((caller_id, callee_id, node.lineno))

        # Remove context when leaving scope (approximate)
        # Note: This is simplified; real implementation needs proper scope tracking

    def _extract_js_calls(self, source: str, symbol_map: dict, file_path: str) -> None:
        """Extract calls from JavaScript/TypeScript source."""
        import re

        # Remove comments
        filtered_lines = []
        in_block_comment = False
        for line in source.split("\n"):
            if "/*" in line:
                in_block_comment = True
            if "*/" in line:
                in_block_comment = False
                continue
            if in_block_comment or line.strip().startswith("//"):
                continue
            filtered_lines.append(line)

        content = "\n".join(filtered_lines)

        # Find function definitions to track context
        func_pattern = r"(?:function|const|let|var)\s+(\w+)\s*="
        functions = {}
        for match in re.finditer(func_pattern, content):
            func_name = match.group(1)
            line_num = content[:match.start()].count("\n") + 1
            func_id = symbol_map.get(func_name, f"{file_path}:{func_name}:{line_num}")
            functions[func_id] = line_num

        # Find method calls: obj.method()
        method_pattern = r"\.(\w+)\s*\("
        for match in re.finditer(method_pattern, content):
            method_name = match.group(1)
            line_num = content[:match.start()].count("\n") + 1

            if method_name in symbol_map:
                callee_id = symbol_map[method_name]

                # Find which function this call belongs to
                current_func = None
                for func_id, func_line in sorted(functions.items(), key=lambda x: -x[1]):
                    if func_line < line_num:
                        current_func = func_id
                        break

                if current_func:
                    self._call_edges.append((current_func, callee_id, line_num))

    def _extract_java_calls(self, source: str, symbol_map: dict, file_path: str) -> None:
        """Extract calls from Java source."""
        import re

        lines = source.split("\n")

        for i, line in enumerate(lines, 1):
            # Skip comments
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("/*"):
                continue

            # Find method calls: obj.method() or ClassName.method()
            method_pattern = r"(?:^|\s)(\w+)\.(\w+)\s*\("
            for match in re.finditer(method_pattern, line):
                class_name = match.group(1)
                method_name = match.group(2)

                # Skip common keywords
                if method_name in ("if", "while", "for", "switch", "class", "this", "super"):
                    continue

                # Build potential symbol name
                full_name = f"{class_name}.{method_name}"
                if full_name in symbol_map:
                    callee_id = symbol_map[full_name]
                    # Note: Java calls require more complex context tracking

    def get_call_edges(self) -> list[tuple[str, str, int]]:
        """Get all extracted call edges."""
        return self._call_edges

    def detect_cycles(self, max_depth: int = 10) -> list[list[str]]:
        """
        Detect circular dependencies in call chains.

        Args:
            max_depth: Maximum chain length to search

        Returns:
            List of cycles (each cycle is a list of symbol IDs)
        """
        cycles = []
        edge_map: dict[str, list[str]] = {}

        # Build adjacency map
        for caller, callee, _ in self._call_edges:
            edge_map.setdefault(caller, []).append(callee)

        def dfs(node: str, path: list[str], visited: set[str]) -> None:
            if node in visited:
                # Found cycle
                cycle_start = path.index(node)
                cycle = path[cycle_start:] + [node]
                cycles.append(cycle)
                return

            if len(path) > max_depth:
                return

            visited.add(node)
            path.append(node)

            for neighbor in edge_map.get(node, []):
                dfs(neighbor, path.copy(), visited.copy())

        # Start DFS from each node
        for node in edge_map.keys():
            dfs(node, [], set())

        return cycles


class KnowledgeDocGenerator:
    """
    Generates knowledge documentation using LLM.

    Creates:
    - Module purpose descriptions
    - Design decision records
    - Architecture rationale
    """

    # Prompt template for LLM
    PROMPT_TEMPLATE = """
You are a code architect analyzing a codebase.

Based on the following symbol definitions and their relationships:

## Symbols
{symbols_info}

## Call Graph (top 50 edges)
{call_graph_info}

## Detected Patterns
{patterns_info}

## Architecture
{architecture_info}

Generate a concise architecture document with:
1. **Module Purpose**: What does this module do?
2. **Key Abstractions**: Main classes/functions and their responsibilities
3. **Data Flow**: How data moves through the system
4. **Design Decisions**: Notable technical choices and why

Focus on implicit knowledge that cannot be gathered from just reading the code.
"""

    def __init__(self, llm_client=None):
        """
        Initialize KnowledgeDocGenerator.

        Args:
            llm_client: Optional LLM client for API calls
        """
        self.llm_client = llm_client

    def generate_module_doc(
        self,
        module_name: str,
        symbols: list,
        edges: list[tuple[str, str, int]] = None,
        patterns: list[ArchitecturePattern] = None,
    ) -> str:
        """
        Generate documentation for a module.

        Args:
            module_name: Name of the module
            symbols: List of SymbolNode in the module
            edges: Optional list of (caller, callee, line) call edges
            patterns: Optional list of detected ArchitecturePattern

        Returns:
            Generated documentation string
        """
        # Format symbols info
        symbols_info = "\n".join([
            f"- {s.kind.value}: {s.name} (line {s.line})\n  Signature: {s.signature}\n  Doc: {s.doc[:100] if s.doc else '(none)'}"
            for s in symbols[:20]
        ]) or "- No symbols found"

        # Format call graph
        call_graph_info = ""
        if edges:
            call_graph_info = "\n".join([
                f"- `{e[0]}` --> `{e[1]}` (line {e[2]})"
                for e in edges[:50]
            ])
        else:
            call_graph_info = "- No call edges"

        # Format patterns
        patterns_info = ""
        if patterns:
            patterns_info = "\n".join([
                f"- **{p.name}** (confidence: {p.confidence:.2f}): {p.description}\n  Keywords: {', '.join(p.detected_keywords)}"
                for p in patterns
            ])
        else:
            patterns_info = "- None detected"

        # Build prompt
        prompt = self.PROMPT_TEMPLATE.format(
            symbols_info=symbols_info,
            call_graph_info=call_graph_info,
            patterns_info=patterns_info,
            architecture_info=f"Module: {module_name}",
        )

        # Call LLM if client available
        if self.llm_client:
            response = self.llm_client.complete_sync(prompt)
            return response

        # Fallback: simple template
        return self._generate_fallback_doc(module_name, symbols, patterns)

    def _generate_fallback_doc(
        self,
        module_name: str,
        symbols: list,
        patterns: list[ArchitecturePattern]
    ) -> str:
        """Generate fallback documentation without LLM."""
        lines = [f"# {module_name}\n"]

        # Overview
        lines.append("## 概述\n")
        lines.append(f"模块 {module_name} 包含 {len(symbols)} 个符号定义。\n")

        # Key symbols
        if symbols:
            lines.append("\n## 关键符号\n")
            for sym in symbols[:5]:
                kind_icon = self._get_kind_icon(sym.kind)
                lines.append(f"- {kind_icon} **{sym.name}**: {sym.doc[:50] if sym.doc else '无描述'}...\n")

        # Patterns
        if patterns:
            lines.append("\n## 检测到的架构模式\n")
            for p in patterns[:3]:
                lines.append(f"- **{p.name}** (置信度: {p.confidence:.1%})\n")

        return "".join(lines)

    def _get_kind_icon(self, kind) -> str:
        """Get icon for symbol kind."""
        icons = {
            "function": "𝑓",
            "class": "𝐶",
            "method": "𝑚",
            "variable": "𝑣",
        }
        return icons.get(kind.value if hasattr(kind, 'value') else str(kind), "•")


class DesignPatternDetector:
    """
    Advanced design pattern detection based on structure and relationships.

    Detects more complex patterns that require analysis of:
    - Class hierarchy
    - Method signatures
    - Design patterns in code
    """

    # Pattern signatures (structural features)
    PATTERN_SIGNATURES = {
        "factory_method": {
            "name": "Factory Method",
            "features": ["creates", "builds", "factory"],
            "structure": "method that returns object type",
        },
        "abstract_factory": {
            "name": "Abstract Factory",
            "features": ["factory", "create"],
            "structure": "interface with factory methods",
        },
        "singleton": {
            "name": "Singleton",
            "features": ["instance", "getInstance", "_instance"],
            "structure": "single instance with global access",
        },
        "observer": {
            "name": "Observer",
            "features": ["notify", "subscribe", "listener", "event"],
            "structure": "publisher-subscriber interface",
        },
        "decorator": {
            "name": "Decorator",
            "features": ["wrap", "decorate", "enhance"],
            "structure": "wrapper around object",
        },
        "strategy": {
            "name": "Strategy",
            "features": ["strategy", "policy", "algorithm"],
            "structure": "interchangeable algorithms",
        },
    }

    def detect_structural_patterns(
        self,
        symbols: list,
        relationships: list[tuple[str, str]] = None
    ) -> list[dict]:
        """
        Detect patterns based on structural features.

        Args:
            symbols: List of SymbolNode
            relationships: Optional list of (source, target) relationships

        Returns:
            List of detected patterns with details
        """
        detected = []

        for pattern_key, pattern_def in self.PATTERN_SIGNATURES.items():
            matches = []

            for sym in symbols:
                sym_lower = sym.name.lower()

                # Check keyword matches
                for keyword in pattern_def["features"]:
                    if keyword in sym_lower:
                        matches.append(sym.id)
                        break

            if len(matches) >= 2:  # At least 2 symbols matching
                detected.append({
                    "pattern": pattern_def["name"],
                    "pattern_key": pattern_key,
                    "matches": matches,
                    "confidence": min(len(matches) / 4, 1.0),  # Simple confidence
                    "description": pattern_def["structure"],
                })

        return detected


def detect_architecture_patterns(symbols: list) -> list[ArchitecturePattern]:
    """
    Convenience function to detect architecture patterns.

    Args:
        symbols: List of SymbolNode

    Returns:
        List of detected ArchitecturePattern
    """
    recognizer = ArchitectureRecognizer()
    return recognizer.recognize(symbols)


def extract_call_chains(
    source: str,
    language: str,
    symbol_map: dict[str, str],
    file_path: str = ""
) -> list[tuple[str, str, int]]:
    """
    Convenience function to extract call chains.

    Args:
        source: Source code
        language: Programming language
        symbol_map: Map of symbol names to IDs
        file_path: File path

    Returns:
        List of (caller, callee, line) tuples
    """
    extractor = CallChainExtractor()
    return extractor.extract_from_source(source, language, symbol_map, file_path)