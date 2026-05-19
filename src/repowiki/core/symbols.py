"""Symbol-level dependency graph for fine-grained code analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
import uuid

import networkx as nx


class SymbolKind(Enum):
    """Symbol type enumeration."""

    # Python
    FUNCTION = "function"
    CLASS = "class"
    MODULE = "module"

    # JavaScript/TypeScript
    METHOD = "method"
    INTERFACE = "interface"

    # Common
    VARIABLE = "variable"
    CONSTANT = "constant"
    PROPERTY = "property"


class SymbolEdgeType(Enum):
    """Symbol relationship type."""

    CALLS = "calls"           # Function/method call
    IMPORTS = "imports"       # Module/package import
    INHERITS = "inherits"     # Class inheritance
    IMPLEMENTS = "implements" # Interface implementation
    USES = "uses"             # Variable/constant usage
    CONTAINS = "contains"     # Member containment
    DECORATES = "decorates"   # Decorator application


@dataclass
class SymbolNode:
    """Symbol node representing a code symbol (function, class, variable)."""

    id: str                                    # Unique ID: "filepath:symbol_name:line"
    name: str                                  # Symbol name
    kind: SymbolKind                           # Symbol type
    file: str                                  # Source file path
    line: int                                  # Definition line number
    end_line: int                              # End line number
    signature: str = ""                         # Function/class signature
    doc: str = ""                               # Documentation string
    wiki_ref: Optional[str] = None              # Associated wiki page reference
    exports: list[str] = field(default_factory=list)   # Symbols exported by this node
    imports: list[str] = field(default_factory=list)   # Symbols imported by this node
    called_by: list[str] = field(default_factory=list) # Symbols that call this
    calls: list[str] = field(default_factory=list)     # Symbols called by this

    @property
    def symbol_id(self) -> str:
        """Get the symbol ID (same as id)."""
        return self.id

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind.value,
            "file": self.file,
            "line": self.line,
            "end_line": self.end_line,
            "signature": self.signature,
            "doc": self.doc,
            "wiki_ref": self.wiki_ref,
            "exports": self.exports,
            "imports": self.imports,
            "called_by": self.called_by,
            "calls": self.calls,
        }


@dataclass
class SymbolEdge:
    """Edge representing relationship between two symbols."""

    source: str                 # Source symbol ID
    target: str                 # Target symbol ID
    edge_type: SymbolEdgeType   # Relationship type
    line: int                   # Line where the relationship occurs
    raw: str = ""               # Raw code snippet

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "source": self.source,
            "target": self.target,
            "edge_type": self.edge_type.value,
            "line": self.line,
            "raw": self.raw,
        }


class SymbolGraph:
    """
    Symbol-level dependency graph.

    Provides fine-grained code analysis at the symbol (function, class, variable)
    level rather than just file level.
    """

    def __init__(self):
        self.symbols: dict[str, SymbolNode] = {}
        self.edges: list[SymbolEdge] = []
        self._caller_index: dict[str, list[str]] = {}  # symbol -> who calls it
        self._callee_index: dict[str, list[str]] = {}   # symbol -> what it calls
        self._file_symbols_index: dict[str, list[str]] = {}  # file -> symbols

    # ========== Node Operations ==========

    def add_symbol(self, symbol: SymbolNode) -> None:
        """Add a symbol node to the graph.

        Args:
            symbol: SymbolNode to add
        """
        self.symbols[symbol.id] = symbol

        # Index by file
        self._file_symbols_index.setdefault(symbol.file, []).append(symbol.id)

    def get_symbol(self, symbol_id: str) -> Optional[SymbolNode]:
        """Get a symbol by its ID.

        Args:
            symbol_id: Symbol ID (format: "filepath:symbol_name:line")

        Returns:
            SymbolNode or None if not found
        """
        return self.symbols.get(symbol_id)

    def get_symbols_by_file(self, file_path: str) -> list[SymbolNode]:
        """Get all symbols defined in a file.

        Args:
            file_path: Path to the file

        Returns:
            List of SymbolNode in the file
        """
        symbol_ids = self._file_symbols_index.get(file_path, [])
        return [self.symbols[sid] for sid in symbol_ids if sid in self.symbols]

    def get_symbols_by_kind(self, kind: SymbolKind) -> list[SymbolNode]:
        """Get all symbols of a specific kind.

        Args:
            kind: SymbolKind to filter by

        Returns:
            List of SymbolNode of the specified kind
        """
        return [s for s in self.symbols.values() if s.kind == kind]

    def remove_symbol(self, symbol_id: str) -> None:
        """Remove a symbol from the graph.

        Args:
            symbol_id: ID of the symbol to remove
        """
        if symbol_id in self.symbols:
            symbol = self.symbols[symbol_id]

            # Remove from file index
            if symbol.file in self._file_symbols_index:
                self._file_symbols_index[symbol.file].remove(symbol_id)

            # Remove from caller/callee indexes
            for callees in self._caller_index.values():
                if symbol_id in callees:
                    callees.remove(symbol_id)
            for callees in self._callee_index.values():
                if symbol_id in callees:
                    callees.remove(symbol_id)

            # Remove symbol
            del self.symbols[symbol_id]

    # ========== Edge Operations ==========

    def add_edge(self, edge: SymbolEdge) -> None:
        """Add an edge to the graph.

        Args:
            edge: SymbolEdge to add
        """
        self.edges.append(edge)

        # Update indexes
        if edge.edge_type == SymbolEdgeType.CALLS:
            self._callee_index.setdefault(edge.source, []).append(edge.target)
            self._caller_index.setdefault(edge.target, []).append(edge.source)

    def get_callers(self, symbol_id: str) -> list[str]:
        """Get all symbols that call the specified symbol.

        Args:
            symbol_id: Symbol ID

        Returns:
            List of symbol IDs that call this symbol
        """
        return self._caller_index.get(symbol_id, [])

    def get_callees(self, symbol_id: str) -> list[str]:
        """Get all symbols called by the specified symbol.

        Args:
            symbol_id: Symbol ID

        Returns:
            List of symbol IDs called by this symbol
        """
        return self._callee_index.get(symbol_id, [])

    def get_edges_by_type(self, edge_type: SymbolEdgeType) -> list[SymbolEdge]:
        """Get all edges of a specific type.

        Args:
            edge_type: SymbolEdgeType to filter by

        Returns:
            List of SymbolEdge of the specified type
        """
        return [e for e in self.edges if e.edge_type == edge_type]

    # ========== Graph Query ==========

    def get_related_symbols(self, symbol_id: str, max_depth: int = 2) -> list[str]:
        """Get symbols related to the specified symbol via BFS traversal.

        Args:
            symbol_id: Starting symbol ID
            max_depth: Maximum traversal depth

        Returns:
            List of related symbol IDs (excluding the starting symbol)
        """
        visited = {symbol_id}
        frontier = [symbol_id]

        for _ in range(max_depth):
            next_frontier = []
            for sid in frontier:
                # Add callees
                for callee in self._callee_index.get(sid, []):
                    if callee not in visited:
                        visited.add(callee)
                        next_frontier.append(callee)
                # Add callers
                for caller in self._caller_index.get(sid, []):
                    if caller not in visited:
                        visited.add(caller)
                        next_frontier.append(caller)
            frontier = next_frontier

        return list(visited - {symbol_id})

    def get_call_chain(self, source_id: str, target_id: str, max_depth: int = 5) -> list[list[str]]:
        """Find all call chains between two symbols.

        Args:
            source_id: Starting symbol ID
            target_id: Target symbol ID
            max_depth: Maximum chain length

        Returns:
            List of call chains (each chain is a list of symbol IDs)
        """
        chains = []

        def dfs(current: str, path: list[str], depth: int):
            if depth > max_depth:
                return
            if current == target_id:
                chains.append(path.copy())
                return

            for callee in self._callee_index.get(current, []):
                if callee not in path:  # Avoid cycles
                    path.append(callee)
                    dfs(callee, path, depth + 1)
                    path.pop()

        dfs(source_id, [source_id], 0)
        return chains

    # ========== Ranking ==========

    def rank_symbols(self, alpha: float = 0.85) -> list[tuple[str, float]]:
        """Rank symbols by importance using PageRank algorithm.

        Args:
            alpha: Damping factor (default 0.85)

        Returns:
            List of (symbol_id, score) sorted by score descending
        """
        if not self.symbols:
            return []

        g = nx.DiGraph()

        # Add nodes
        for sid in self.symbols:
            g.add_node(sid)

        # Add edges (only CALLS edges for PageRank)
        for edge in self.edges:
            if edge.edge_type == SymbolEdgeType.CALLS:
                g.add_edge(edge.source, edge.target)

        try:
            scores = nx.pagerank(g, alpha=alpha)
        except Exception:
            # Fallback: uniform scores
            scores = {n: 1.0 / len(g) for n in g.nodes()}

        return sorted(scores.items(), key=lambda x: -x[1])

    def get_core_symbols(self, top_n: int = 20) -> list[SymbolNode]:
        """Get the top N most important symbols by PageRank.

        Args:
            top_n: Number of symbols to return

        Returns:
            List of SymbolNode sorted by importance
        """
        ranked = self.rank_symbols()
        return [self.symbols[sid] for sid, _ in ranked[:top_n] if sid in self.symbols]

    # ========== Analysis ==========

    def get_symbol_density(self, file_path: str) -> int:
        """Get the number of symbols defined in a file.

        Args:
            file_path: Path to the file

        Returns:
            Number of symbols in the file
        """
        return len(self._file_symbols_index.get(file_path, []))

    def get_import_graph(self) -> dict[str, set[str]]:
        """Get module-level import dependencies.

        Returns:
            Dict mapping module name to set of dependent modules
        """
        deps: dict[str, set[str]] = {}

        for edge in self.edges:
            if edge.edge_type == SymbolEdgeType.IMPORTS:
                src_symbol = self.symbols.get(edge.source)
                tgt_symbol = self.symbols.get(edge.target)

                if src_symbol and tgt_symbol:
                    src_mod = self._get_module(src_symbol.file)
                    tgt_mod = self._get_module(tgt_symbol.file)

                    if src_mod != tgt_mod:
                        deps.setdefault(src_mod, set()).add(tgt_mod)

        return deps

    def to_mermaid(self, top_n: int = 50) -> str:
        """Generate Mermaid diagram of symbol relationships.

        Args:
            top_n: Number of top symbols to include

        Returns:
            Mermaid diagram string
        """
        lines = ["graph TD"]

        # Get top symbols by PageRank
        ranked = self.rank_symbols()[:top_n]
        top_symbols = {sid: score for sid, score in ranked}

        if not top_symbols:
            return "\n".join(lines)

        # Group by file
        file_groups: dict[str, list[str]] = {}
        for sid in top_symbols:
            symbol = self.symbols.get(sid)
            if symbol:
                file_groups.setdefault(symbol.file, []).append(sid)

        # Add subgraphs for each file
        for file_path, symbol_ids in sorted(file_groups.items(), key=lambda x: -len(x[1])):
            safe_name = self._mermaid_id(Path(file_path).stem)
            lines.append(f"  subgraph {safe_name}")
            for sid in symbol_ids:
                symbol = self.symbols.get(sid)
                if symbol:
                    node_id = self._mermaid_id(sid)
                    kind_icon = self._get_kind_icon(symbol.kind)
                    lines.append(f"    {node_id}[{kind_icon} {symbol.name}]")
            lines.append("  end")

        # Add edges
        lines.append("")
        seen_edges = set()
        for edge in self.edges:
            if edge.source in top_symbols and edge.target in top_symbols:
                edge_key = (edge.source, edge.target)
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    src_id = self._mermaid_id(edge.source)
                    tgt_id = self._mermaid_id(edge.target)
                    edge_label = self._get_edge_label(edge.edge_type)
                    lines.append(f"  {src_id} -->|{edge_label}| {tgt_id}")

        return "\n".join(lines)

    # ========== Private Helpers ==========

    def _get_module(self, file_path: str) -> str:
        """Extract module name (top-level directory) from file path.

        Args:
            file_path: File path

        Returns:
            Module name
        """
        parts = Path(file_path).parts
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
        # Replace invalid characters with underscore
        safe = re.sub(r"[^a-zA-Z0-9_]", "_", name)
        # Ensure it doesn't start with a number
        if safe[0].isdigit():
            safe = "s_" + safe
        return safe[:50]  # Limit length

    def _get_kind_icon(self, kind: SymbolKind) -> str:
        """Get icon character for symbol kind."""
        icons = {
            SymbolKind.FUNCTION: "𝑓",
            SymbolKind.CLASS: "𝐶",
            SymbolKind.METHOD: "𝑚",
            SymbolKind.VARIABLE: "𝑣",
            SymbolKind.CONSTANT: "𝚌",
            SymbolKind.PROPERTY: "𝑝",
            SymbolKind.INTERFACE: "𝐼",
            SymbolKind.MODULE: "𝑀",
        }
        return icons.get(kind, "•")

    def _get_edge_label(self, edge_type: SymbolEdgeType) -> str:
        """Get label for edge type."""
        labels = {
            SymbolEdgeType.CALLS: "calls",
            SymbolEdgeType.IMPORTS: "imports",
            SymbolEdgeType.INHERITS: "inherits",
            SymbolEdgeType.IMPLEMENTS: "implements",
            SymbolEdgeType.USES: "uses",
            SymbolEdgeType.CONTAINS: "contains",
            SymbolEdgeType.DECORATES: "decorates",
        }
        return labels.get(edge_type, "")

    # ========== Serialization ==========

    def to_dict(self) -> dict:
        """Convert the entire graph to a dictionary.

        Returns:
            Dictionary representation of the graph
        """
        return {
            "symbols": {sid: s.to_dict() for sid, s in self.symbols.items()},
            "edges": [e.to_dict() for e in self.edges],
            "stats": {
                "total_symbols": len(self.symbols),
                "total_edges": len(self.edges),
                "by_kind": {
                    kind.value: len(self.get_symbols_by_kind(kind))
                    for kind in SymbolKind
                },
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> SymbolGraph:
        """Create a SymbolGraph from a dictionary.

        Args:
            data: Dictionary representation

        Returns:
            SymbolGraph instance
        """
        graph = cls()

        # Restore symbols
        for sid, sym_data in data.get("symbols", {}).items():
            symbol = SymbolNode(
                id=sym_data["id"],
                name=sym_data["name"],
                kind=SymbolKind(sym_data["kind"]),
                file=sym_data["file"],
                line=sym_data["line"],
                end_line=sym_data["end_line"],
                signature=sym_data.get("signature", ""),
                doc=sym_data.get("doc", ""),
                wiki_ref=sym_data.get("wiki_ref"),
                exports=sym_data.get("exports", []),
                imports=sym_data.get("imports", []),
                called_by=sym_data.get("called_by", []),
                calls=sym_data.get("calls", []),
            )
            graph.add_symbol(symbol)

        # Restore edges
        for edge_data in data.get("edges", []):
            edge = SymbolEdge(
                source=edge_data["source"],
                target=edge_data["target"],
                edge_type=SymbolEdgeType(edge_data["edge_type"]),
                line=edge_data["line"],
                raw=edge_data.get("raw", ""),
            )
            graph.add_edge(edge)

        return graph

    def summary(self) -> str:
        """Get a summary of the symbol graph.

        Returns:
            Human-readable summary string
        """
        lines = [
            f"SymbolGraph Summary:",
            f"  Total symbols: {len(self.symbols)}",
            f"  Total edges: {len(self.edges)}",
            f"  By kind:",
        ]

        for kind in SymbolKind:
            count = len(self.get_symbols_by_kind(kind))
            if count > 0:
                lines.append(f"    {kind.value}: {count}")

        lines.append(f"  Files with symbols: {len(self._file_symbols_index)}")

        return "\n".join(lines)