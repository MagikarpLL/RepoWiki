"""scan a project directory and collect file metadata for analysis."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from repowiki.config import DEFAULT_MAX_FILE_SIZE, DEFAULT_MAX_FILES
from repowiki.core.models import FileChunk, FileInfo

logger = logging.getLogger(__name__)

_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".idea", ".vscode", ".next", "dist", "build", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "egg-info", ".turbo", "coverage",
    ".cache", "vendor", "target", "__snapshots__", ".svn", ".hg",
    ".gradle", ".m2", "Pods", ".dart_tool", ".pub-cache",
}

_SKIP_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv", ".flac",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar", ".xz",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".dat",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".pyc", ".pyo", ".class", ".o", ".obj",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".db", ".sqlite", ".sqlite3",
    ".lock",
    ".min.js", ".min.css",
    ".map",
    ".wasm",
}

_MINIFIED_SOURCE_EXTS = {".js", ".mjs", ".cjs", ".css"}

_LANG_MAP = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".mts": "typescript",
    ".jsx": "jsx", ".tsx": "tsx",
    ".html": "html", ".htm": "html",
    ".css": "css", ".scss": "scss", ".less": "less",
    ".json": "json", ".jsonc": "json",
    ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown", ".mdx": "markdown",
    ".txt": "text", ".rst": "rst",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin", ".kts": "kotlin",
    ".scala": "scala",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".r": "r", ".R": "r",
    ".sql": "sql",
    ".swift": "swift",
    ".lua": "lua",
    ".dart": "dart",
    ".vue": "vue",
    ".svelte": "svelte",
    ".zig": "zig",
    ".nim": "nim",
    ".ex": "elixir", ".exs": "elixir",
    ".erl": "erlang",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".clj": "clojure",
    ".proto": "protobuf",
    ".graphql": "graphql", ".gql": "graphql",
    ".tf": "terraform", ".hcl": "hcl",
    ".prisma": "prisma",
    ".astro": "astro",
    ".cfg": "ini", ".ini": "ini",
    ".env": "text",
    ".cmake": "cmake",
    ".gradle": "gradle",
    ".dockerfile": "dockerfile",
}

# Languages that are considered "code" - these get processed even if large
_CODE_LANGUAGES = {
    "python", "javascript", "typescript", "jsx", "tsx",
    "go", "rust", "java", "kotlin", "scala",
    "c", "cpp", "csharp", "ruby", "php", "swift",
    "lua", "dart", "vue", "svelte", "zig", "nim",
    "elixir", "erlang", "haskell", "ocaml", "clojure",
    "shell", "sql",
}


def _is_code_file_by_ext(path: str) -> bool:
    """Check if file extension indicates a code file (before reading content)."""
    ext = Path(path).suffix.lower()
    return ext in _LANG_MAP and _LANG_MAP[ext] in _CODE_LANGUAGES

# files that give the LLM project context -- always read in full
_CONFIG_FILES = {
    "requirements.txt", "setup.py", "setup.cfg", "pyproject.toml",
    "package.json", "Cargo.toml", "go.mod", "go.sum",
    "Makefile", "CMakeLists.txt",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    ".env.example", "config.py", "config.yaml", "config.json", "config.toml",
    "README.md", "README.rst", "README.txt", "README",
    "tsconfig.json", "vite.config.ts", "vite.config.js",
    "webpack.config.js", "rollup.config.js",
    "Gemfile", "build.gradle", "pom.xml",
    ".eslintrc.json", ".prettierrc",
}

# files that are likely entry points
_ENTRYPOINT_NAMES = {
    "main.py", "app.py", "index.py", "server.py", "run.py", "__main__.py",
    "main.go", "main.rs", "main.ts", "main.js",
    "index.ts", "index.js", "index.tsx", "index.jsx",
    "App.tsx", "App.jsx", "App.vue", "App.svelte",
    "manage.py", "wsgi.py", "asgi.py",
}

_ENTRYPOINT_DIRS = {"cmd", "bin", "scripts", "entrypoints"}


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:1024]


def _has_skipped_suffix(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(ext) for ext in _SKIP_EXTS)


def _looks_minified_source(path: str, text: str) -> bool:
    if Path(path).suffix.lower() not in _MINIFIED_SOURCE_EXTS:
        return False

    lines = text.splitlines() or [text]
    longest = max(len(line) for line in lines)
    if longest < 1000:
        return False

    non_empty = [line for line in lines if line.strip()]
    return len(non_empty) <= 5 or longest > len(text) * 0.5


def detect_language(path: str) -> str:
    name = Path(path).name.lower()
    if name == "dockerfile" or name.startswith("dockerfile."):
        return "dockerfile"
    if name == "makefile":
        return "makefile"
    ext = Path(path).suffix.lower()
    return _LANG_MAP.get(ext, "unknown")


def _is_entrypoint(rel_path: str) -> bool:
    parts = Path(rel_path).parts
    name = parts[-1]
    if name in _ENTRYPOINT_NAMES:
        return True
    if len(parts) >= 2 and parts[-2] in _ENTRYPOINT_DIRS:
        return True
    return False


# Chunking thresholds
MAX_UNCHUNKED_SIZE = 4000  # chars, files larger than this get chunked
PREVIEW_LINES_FOR_LARGE = 200  # preview lines for chunked files


def _chunk_by_structure(content: str) -> list[FileChunk]:
    """Split a large file into chunks at structural boundaries (class, function, method, etc.).

    This preserves code structure integrity - chunks won't cut in the middle of a function
    or class definition. Each chunk is a complete structural unit.
    """
    import re

    from repowiki.core.models import FileChunk

    # Multi-language structural patterns
    STRUCT_PATTERNS = [
        # Classes (Java, Python, TypeScript, etc.)
        (r'^class\s+(\w+)', 'class'),
        (r'^public\s+class\s+(\w+)', 'class'),
        (r'^private\s+class\s+(\w+)', 'class'),
        (r'^protected\s+class\s+(\w+)', 'class'),
        (r'^(?:abstract\s+)?class\s+(\w+)', 'class'),
        # Python functions/methods
        (r'^def\s+(\w+)', 'function'),
        (r'^async\s+def\s+(\w+)', 'function'),
        # JavaScript/TypeScript functions
        (r'^function\s+(\w+)', 'function'),
        # Go functions
        (r'^func\s+(\w+)', 'function'),
        # Java/Kotlin methods (with various modifiers)
        (r'^(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?(?:\w+\s+)+\w+\s*\([^(]*\)', 'method'),
        # Kotlin extension functions
        (r'^(?:fun\s+)?\w+\s*\.\w+\s*\(', 'method'),
        # Rust functions
        (r'^pub\s+fn\s+(\w+)', 'function'),
        (r'^fn\s+(\w+)', 'function'),
        # Interfaces
        (r'^interface\s+(\w+)', 'interface'),
        # Enums
        (r'^enum\s+(\w+)', 'enum'),
        # Structs
        (r'^struct\s+(\w+)', 'struct'),
        # C/C++ structs and classes
        (r'^(?:struct|class)\s+\w+', 'class'),
    ]

    compiled_patterns = [(re.compile(p, re.MULTILINE), stype) for p, stype in STRUCT_PATTERNS]

    lines = content.split('\n')
    total_lines = len(lines)

    chunks = []
    current_lines = []
    current_len = 0
    current_struct = None
    current_name = None

    for i, line in enumerate(lines):
        line_stripped = line.strip()

        # Detect structural boundary
        matched = None
        for pattern, stype in compiled_patterns:
            if pattern.match(line_stripped):
                matched = stype
                # Try to extract name
                for p_str, _ in STRUCT_PATTERNS:
                    m = re.match(p_str, line_stripped)
                    if m and m.groups():
                        current_name = m.group(1)
                        break
                if current_name is None:
                    current_name = stype
                break

        is_struct_boundary = matched is not None

        # Decide whether to split
        should_split = False
        if current_len >= MAX_UNCHUNKED_SIZE and current_lines:
            should_split = True
        if is_struct_boundary and current_len >= MAX_UNCHUNKED_SIZE * 0.6 and current_lines:
            should_split = True

        if should_split:
            start = i - len(current_lines)
            chunks.append(FileChunk(
                chunk_id=f"chunk-{len(chunks)}",
                content='\n'.join(current_lines),
                start_line=start + 1,  # 1-indexed
                end_line=i,
                chunk_type=current_struct or "block",
                chunk_name=current_name or f"block-{len(chunks)}"
            ))
            current_lines = []
            current_len = 0
            current_struct = None
            current_name = None

        current_lines.append(line)
        current_len += len(line) + 1

        if matched:
            current_struct = matched

    # Save last chunk
    if current_lines:
        start = total_lines - len(current_lines)
        chunks.append(FileChunk(
            chunk_id=f"chunk-{len(chunks)}",
            content='\n'.join(current_lines),
            start_line=start + 1,
            end_line=total_lines,
            chunk_type=current_struct or "tail",
            chunk_name=current_name or "tail"
        ))

    return chunks


def build_file_tree(files: list[FileInfo], max_lines: int = 200) -> str:
    """render an ascii tree from the file list, similar to `tree` command."""
    # collect unique directories + files
    entries: set[str] = set()
    for f in files:
        entries.add(f.path)
        parts = Path(f.path).parts
        for i in range(1, len(parts)):
            entries.add(str(Path(*parts[:i])) + "/")

    sorted_entries = sorted(entries)
    lines = []
    for entry in sorted_entries[:max_lines]:
        depth = entry.rstrip("/").count(os.sep)
        indent = "  " * depth
        name = Path(entry.rstrip("/")).name
        if entry.endswith("/"):
            name += "/"
        lines.append(f"{indent}{name}")

    if len(sorted_entries) > max_lines:
        lines.append(f"  ... and {len(sorted_entries) - max_lines} more entries")
    return "\n".join(lines)


def scan_directory(
    root: str | Path,
    max_file_size: int = DEFAULT_MAX_FILE_SIZE,
    max_files: int = DEFAULT_MAX_FILES,
    preview_lines: int = 80,
) -> list[FileInfo]:
    """walk a project directory and return file info with previews.

    Uses parallel processing for file I/O with ThreadPoolExecutor.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Not a directory: {root}")

    # First pass: collect all candidate file paths (fast, sequential)
    candidate_paths: list[tuple[str, Path]] = []  # (rel_path, full_path)

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS and not d.endswith(".egg-info")
        ]

        for fname in filenames:
            full = Path(dirpath) / fname
            rel = str(full.relative_to(root))

            if full.is_symlink():
                continue

            if _has_skipped_suffix(full):
                continue

            candidate_paths.append((rel, full))

            if len(candidate_paths) >= max_files * 2:  # Collect more than needed for filtering
                break

        if len(candidate_paths) >= max_files * 2:
            break

    # Second pass: parallel file processing
    import os as os_module
    num_workers = min(8, (os_module.cpu_count() or 4))
    from concurrent.futures import ThreadPoolExecutor

    def process_file(rel_and_full: tuple[str, Path]) -> FileInfo | None:
        """Process a single file and return FileInfo or None if skipped."""
        rel, full = rel_and_full

        try:
            size = full.stat().st_size
        except OSError:
            return None

        if size == 0:
            return None
        if size > max_file_size and not _is_code_file_by_ext(rel):
            return None

        try:
            raw = full.read_bytes()
        except OSError:
            return None

        if _is_binary(raw):
            return None

        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            return None

        if _looks_minified_source(rel, text):
            return None

        lang = detect_language(rel)
        fname = os.path.basename(rel)
        is_cfg = fname in _CONFIG_FILES
        is_entry = _is_entrypoint(rel)
        line_count = text.count("\n") + 1

        # Large files get structural chunking for accurate line references
        if len(text) > MAX_UNCHUNKED_SIZE:
            chunks = _chunk_by_structure(text)
            preview = "\n".join(text.splitlines()[:PREVIEW_LINES_FOR_LARGE])
            return FileInfo(
                path=rel,
                size=size,
                language=lang,
                lines=line_count,
                preview=preview,
                content=text,
                is_config=is_cfg,
                is_entrypoint=is_entry,
                is_chunked=True,
                chunks=chunks,
            )
        else:
            # Small files: keep full content, standard preview
            preview = text if is_cfg or is_entry else "\n".join(text.splitlines()[:preview_lines])
            return FileInfo(
                path=rel,
                size=size,
                language=lang,
                lines=line_count,
                preview=preview,
                content=text,
                is_config=is_cfg,
                is_entrypoint=is_entry,
                is_chunked=False,
                chunks=[],
            )

    # Process files in parallel
    results: list[FileInfo] = []
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        file_infos = list(executor.map(process_file, candidate_paths))
        for fi in file_infos:
            if fi is not None:
                results.append(fi)
                if len(results) >= max_files:
                    break

    # sort: configs first, then entrypoints, then alphabetical
    def _sort_key(f: FileInfo) -> tuple:
        if f.is_config:
            return (0, f.path)
        if f.is_entrypoint:
            return (1, f.path)
        return (2, f.path)

    results.sort(key=_sort_key)
    return results[:max_files]
