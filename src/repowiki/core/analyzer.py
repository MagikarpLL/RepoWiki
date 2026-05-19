"""orchestrates the multi-step LLM analysis pipeline."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from repowiki.core.cache import Cache, content_hash
from repowiki.core.graph import DependencyGraph
from repowiki.core.models import (
    ArchitectureDiagram,
    DocCategory,
    DocGenerationRecord,
    DocItem,
    DocMap,
    FileInfo,
    GeneratedDoc,
    ModuleDoc,
    ProjectContext,
    ProjectOverview,
    ReadingGuide,
    WikiData,
)
from repowiki.llm.client import LLMClient
from repowiki.llm.prompts import (
    build_architecture_prompt,
    build_category_index_prompt,
    build_docmap_prompt,
    build_doc_prompt,
    build_module_prompt,
    build_overview_prompt,
    build_reading_guide_prompt,
    extract_json,
    extract_json_content,
    _build_structure_summary,
)

logger = logging.getLogger(__name__)


# English to Chinese category name mappings for ID normalization
_EN_TO_ZH_CATEGORIES = {
    "guide": "指南", "guides": "指南",
    "quickstart": "快速开始", "quick-start": "快速开始", "getting-started": "快速开始",
    "installation": "安装配置", "install": "安装配置", "setup": "安装配置", "config": "安装配置", "configuration": "安装配置",
    "tutorials": "教程指南", "tutorial": "教程指南", "tutoriales": "教程指南",
    "reference": "参考手册", "references": "参考手册",
    "api": "API参考", "api-reference": "API参考",
    "best-practices": "最佳实践", "bestpractice": "最佳实践",
    "troubleshooting": "故障排查", "trouble-shooting": "故障排查", "faq": "常见问题",
    "common": "常见问题", "errors": "错误码",
    "architecture": "架构参考", "core": "核心组件", "components": "核心组件",
    "payment": "支付集成", "payments": "支付集成", "pay": "支付集成",
    "alipay": "支付宝", "wxpay": "微信支付", "wechat": "微信支付", "wechatpay": "微信支付",
    "jdpay": "京东支付", "jd": "京东支付",
    "paypal": "PayPal", "stripe": "Stripe支付",
    "development": "开发指南", "dev": "开发指南",
    "framework": "框架集成", "integration": "框架集成", "integrations": "框架集成",
    "utils": "工具类", "utilities": "工具类", "tools": "工具类",
    "enums": "枚举定义", "enumerations": "枚举定义",
    "advanced": "高级话题",
    "security": "安全指南",
    "performance": "性能优化",
    "deployment": "部署指南",
    "contributing": "贡献指南",
    "changelog": "更新日志",
}

# Chinese to English category name mappings (reverse)
_ZH_TO_EN_CATEGORIES = {v: k for k, v in _EN_TO_ZH_CATEGORIES.items()}


def _normalize_doc_id_to_chinese(doc_id: str, category_mapping: dict[str, str]) -> str:
    """Convert an English doc_id to Chinese if it matches known category names."""
    parts = doc_id.split("/")
    normalized_parts = []
    for part in parts:
        # Check each part against the mapping
        lower_part = part.lower()
        if lower_part in category_mapping:
            chinese = category_mapping[lower_part]
            # Preserve original casing for first char if it was uppercase
            if part[0].isupper() and chinese:
                chinese = chinese[0].upper() + chinese[1:]
            normalized_parts.append(chinese)
        else:
            normalized_parts.append(part)
    return "/".join(normalized_parts)


def detect_project_type(files: list[FileInfo]) -> str:
    """Detect project type from file list.

    Returns one of: backend-app, frontend-app, cli-tool, library,
    full-stack, monorepo, or unknown
    """
    has_frontend_markers = any(
        f.path in ("package.json", "tsconfig.json", "vite.config.ts", "webpack.config.js")
        or f.path.startswith("src/") and any(ext in f.path for ext in (".tsx", ".jsx", ".vue", ".svelte"))
        for f in files
    )

    has_backend_markers = any(
        f.path in ("requirements.txt", "pyproject.toml", "setup.py", "Gemfile", "go.mod", "Cargo.toml")
        or "app.py" in f.path or "server.py" in f.path
        or f.path.startswith("src/") and f.language in ("python", "go", "rust")
        for f in files
    )

    has_cli_markers = any(
        f.path in ("setup.py", "pyproject.toml")
        and f.content
        and ("console_scripts" in f.content or "entry_points" in f.content or "scripts" in f.content)
        for f in files
    )

    has_monorepo_markers = any(
        "packages/" in f.path or "workspace" in f.path or "monorepo" in f.path.lower()
        for f in files
    )

    has_ui_files = any(
        f.path.startswith("src/") and any(ext in f.path for ext in (".tsx", ".jsx", ".vue", ".svelte"))
        for f in files
    )

    if has_monorepo_markers:
        return "monorepo"
    if has_frontend_markers and has_backend_markers:
        return "full-stack"
    if has_frontend_markers or has_ui_files:
        return "frontend-app"
    if has_backend_markers:
        return "backend-app"
    if has_cli_markers:
        return "cli-tool"

    # Check if it's a library (mostly .py files in src/ or lib/)
    code_files = [f for f in files if f.language in ("python", "rust", "go") and not f.is_config]
    if len(code_files) > 5:
        return "library"

    return "unknown"


class Analyzer:
    """runs the full wiki generation pipeline."""

    def __init__(
        self,
        llm: LLMClient,
        cache: Cache,
        language: str = "en",
        concurrency: int = 5,
        retry_failed: bool = True,
        generation_mode: str = "full",
        generation_record: DocGenerationRecord | None = None,
    ):
        self.llm = llm
        self.cache = cache
        self.language = language
        self._sem = asyncio.Semaphore(concurrency)
        self.retry_failed = retry_failed
        self.generation_mode = generation_mode
        self.generation_record = generation_record or DocGenerationRecord()

    async def _call_llm_with_retry(
        self,
        messages: list[dict],
        *,
        max_tokens: int = 4096,
        max_retries: int = 3,
    ) -> str:
        """Call LLM with exponential backoff retry on failure."""
        for attempt in range(max_retries):
            try:
                return await self.llm.complete(messages, max_tokens=max_tokens)
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.warning("LLM call failed after %d attempts: %s", max_retries, e)
                    return ""
                wait_time = 2 ** attempt
                logger.warning(
                    "LLM call failed (attempt %d/%d), retrying in %ds: %s",
                    attempt + 1, max_retries, wait_time, e,
                )
                await asyncio.sleep(wait_time)
        return ""

    async def analyze(
        self,
        project: ProjectContext,
        on_progress: Callable[[str], None] | None = None,
    ) -> WikiData:
        """Run the hierarchical wiki generation pipeline.

        New order (optimized):
        - Stage 0: Dependency graph building
        - Stage 1: DocMap (structure only)
        - Stage 2: Generate all docs
        - Stage 3: Module docs (for reading guide)
        - Stage 4: Architecture + Reading guide
        - Stage 5: Overview (based on generated docs - quality optimized)
        """

        def progress(msg: str):
            if on_progress:
                on_progress(msg)

        # Stage 0: Dependency graph building
        progress("[1/6] Building dependency graph...")
        graph = DependencyGraph.build_from_project(project)
        progress(f"  → Found {len(project.files)} files, {len(graph.get_core_files(10))} core files")

        # Stage 1: Generate DocMap (structure + file groupings, NO content)
        progress("[2/6] Analyzing project structure and creating doc map...")
        tree_hash = content_hash(project.file_tree)
        doc_map = await self._generate_doc_map(project, graph, tree_hash, progress)
        progress(f"  → Created doc map: {len(doc_map.categories)} categories, {len(doc_map.docs)} docs")

        # Stage 2: Generate all docs in parallel with semaphore control
        doc_count = len(doc_map.docs)
        progress("[3/6] Generating docs in parallel (with retry support)...")
        generated_docs = await self._generate_docs_parallel(
            doc_map, project, graph, None, progress,
            max_retries=2 if self.retry_failed else 0
        )
        success_count = sum(1 for g in generated_docs if g and "Warning" not in g.content)
        failed_count = doc_count - success_count
        progress(f"  → Generated {success_count}/{doc_count} docs successfully" +
                 (f", {failed_count} failed" if failed_count > 0 else ""))

        # Stage 4: Module docs (backward compat with WikiBuilder, also needed by reading guide)
        progress("[4/6] Generating module docs...")
        modules_map = self._group_into_modules(project.files)
        module_docs = await self._generate_module_docs_legacy(
            modules_map, project.name, project, graph, progress
        )
        progress(f"  → Generated {len(module_docs)} module docs")

        # Stage 4: Architecture and reading guide (run in parallel since they're independent)
        progress("[5/6] Generating architecture and reading guide...")
        key_files_text = self._build_key_files_context(project)

        architecture, reading_guide = await asyncio.gather(
            self._generate_architecture(project, key_files_text, tree_hash),
            self._generate_reading_guide(project, doc_map, module_docs, tree_hash)
        )
        progress(f"  → Architecture: {architecture.architecture_type or 'not detected'}")
        progress(f"  → Reading guide: {len(reading_guide.steps)} steps")

        # Stage 5: Overview (moved to last - based on all generated docs for higher quality)
        progress("[6/6] Generating project overview from docs...")
        overview = await self._generate_overview_from_docs(
            project, doc_map, generated_docs, module_docs, architecture, progress
        )
        progress(f"  → Overview: {overview.name or project.name} ({overview.project_type or 'unknown type'})")

        progress("✅ Wiki generation complete!")
        return WikiData(
            overview=overview,
            modules=module_docs,
            architecture=architecture,
            reading_guide=reading_guide,
            file_index={},
            doc_map=doc_map,
            generated_docs=generated_docs,
        )

    def _build_key_files_context(self, project: ProjectContext) -> str:
        """collect config files and entrypoints for the overview prompt."""
        parts = []
        for f in project.files:
            if f.is_config or f.is_entrypoint:
                content = f.content if f.content else f.preview
                # truncate large files
                if len(content) > 4096:
                    content = content[:4096] + "\n... (truncated)"
                parts.append(f"### {f.path}\n```{f.language}\n{content}\n```")
        return "\n\n".join(parts)

    async def _generate_overview(
        self, project: ProjectContext, key_files: str, tree_hash: str
    ) -> ProjectOverview:
        cache_key = f"overview:{tree_hash}"
        cached = await self.cache.get(cache_key)
        if cached:
            try:
                return ProjectOverview(**cached)
            except Exception as e:
                logger.debug("Failed to parse cached overview, recalculating: %s", e)

        messages = build_overview_prompt(project.file_tree, key_files, self.language)
        raw = await self._call_llm_with_retry(messages, max_tokens=4096)

        # DEBUG: Log raw response details
        logger.debug("Overview LLM raw response: length=%d", len(raw) if raw else 0)
        if raw:
            logger.debug("Overview raw[:150] = %r", raw[:150])
            logger.debug("Overview raw[-150:] = %r", raw[-150:])

        data = extract_json(raw)

        # DEBUG: Log extract_json result
        if data is None:
            logger.debug("Overview extract_json returned None")
        elif not isinstance(data, dict):
            logger.debug("Overview extract_json returned non-dict: %s", type(data))
        else:
            logger.debug("Overview extract_json success: keys=%s", list(data.keys()))

        if not data or not isinstance(data, dict):
            logger.warning("Failed to parse overview JSON. Raw response length: %d, full content:\n%s",
                len(raw) if raw else 0, raw if raw else "empty")
            return ProjectOverview(name=project.name)

        filtered = {k: v for k, v in data.items() if k in ProjectOverview.model_fields}
        try:
            overview = ProjectOverview(**filtered)
        except Exception:
            overview = ProjectOverview(name=project.name)
        await self.cache.put(cache_key, overview.model_dump())
        return overview

    async def _generate_overview_from_docs(
        self,
        project: ProjectContext,
        doc_map: DocMap,
        generated_docs: list[GeneratedDoc],
        module_docs: list[ModuleDoc],
        architecture: ArchitectureDiagram,
        progress: Callable[[str], None],
    ) -> ProjectOverview:
        """Stage 5: Generate overview based on all generated docs for higher quality.

        This is called AFTER all docs are generated, so we can extract:
        - Project name from doc IDs
        - Tech stack from module docs
        - Key features from successful doc summaries
        - Project type from architecture
        """
        cache_key = f"overview:v2:{content_hash(str(len(generated_docs)))}"
        cached = await self.cache.get(cache_key)
        if cached:
            try:
                return ProjectOverview(**cached)
            except Exception:
                pass

        # Build context from generated docs
        doc_summaries = []
        for doc in generated_docs:
            if doc and doc.content and "Warning" not in doc.content:
                # Extract title and first section content
                lines = doc.content.split("\n")
                title = ""
                for line in lines:
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
                if title:
                    # Get first meaningful paragraph (skip TOC, cite, etc.)
                    first_para = ""
                    in_para = False
                    for line in lines:
                        stripped = line.strip()
                        if stripped.startswith("## ") or stripped.startswith("**图表") or stripped.startswith("**章节"):
                            break
                        if stripped and len(stripped) > 50:
                            in_para = True
                            first_para = stripped
                            break
                    doc_summaries.append(f"- **{title}**: {first_para[:200]}..." if first_para else f"- **{title}**")

        modules_summaries = "\n".join([f"- **{m.name}**: {m.purpose}" for m in module_docs[:10]])

        # Build tech stack from project files
        tech_stack_parts = []
        for f in project.files[:30]:
            if f.is_config:
                if f.path.endswith(".py"):
                    tech_stack_parts.append('{"name": "Python", "category": "language"}')
                elif f.path.endswith(".js"):
                    tech_stack_parts.append('{"name": "JavaScript", "category": "language"}')
                elif f.path.endswith(".ts"):
                    tech_stack_parts.append('{"name": "TypeScript", "category": "language"}')
                elif f.path.endswith(".java"):
                    tech_stack_parts.append('{"name": "Java", "category": "language"}')
                elif f.path.endswith(".go"):
                    tech_stack_parts.append('{"name": "Go", "category": "language"}')
        tech_stack_str = ", ".join(tech_stack_parts[:10])

        prompt = f"""Based on the generated documentation for project '{project.name}', provide a comprehensive overview:

Project Documentation Summary:
{chr(10).join(doc_summaries[:20])}

Module Structure:
{modules_summaries}

Architecture Type: {architecture.architecture_type or 'unknown'}

Output JSON with:
- name: project name
- one_liner: what this project does in one sentence (max 20 words)
- description: 2-3 paragraphs explaining the project in plain language
- project_type: one of: backend-app, frontend-app, cli-tool, library, full-stack, monorepo, or unknown
- tech_stack: key technologies used
- key_features: main features based on the docs
- setup_instructions: basic setup steps
"""

        messages = [
            {"role": "system", "content": f"You are a senior software engineer. Respond in {self.language}."},
            {"role": "user", "content": prompt},
        ]
        raw = await self._call_llm_with_retry(messages, max_tokens=4096)
        data = extract_json(raw)
        if not data or not isinstance(data, dict):
            logger.warning("Failed to parse overview from docs. Raw: %d", len(raw) if raw else 0)
            return ProjectOverview(name=project.name)

        filtered = {k: v for k, v in data.items() if k in ProjectOverview.model_fields}
        try:
            overview = ProjectOverview(**filtered)
        except Exception:
            overview = ProjectOverview(name=project.name)
        await self.cache.put(cache_key, overview.model_dump())
        return overview

    def _group_into_modules(self, files: list[FileInfo]) -> dict[str, list[FileInfo]]:
        """group files by their top-level directory."""
        from pathlib import Path

        modules: dict[str, list[FileInfo]] = {}
        for f in files:
            parts = Path(f.path).parts
            if len(parts) == 1:
                # root-level files go into a "root" module
                modules.setdefault("root", []).append(f)
            else:
                # use the first directory as module name
                mod = parts[0]
                # if it's a common wrapper like "src", use the second level
                if mod in ("src", "lib", "pkg", "internal", "app") and len(parts) > 2:
                    mod = parts[1]
                modules.setdefault(mod, []).append(f)
        return modules

    async def _analyze_modules(
        self,
        modules: dict[str, list[FileInfo]],
        project_summary: str,
        project: ProjectContext,
        progress: Callable[[str], None],
    ) -> list[ModuleDoc]:
        tasks = []
        for name, files in modules.items():
            tasks.append(self._analyze_one_module(name, files, project_summary, project))

        results = []
        for i, coro in enumerate(asyncio.as_completed(tasks)):
            doc = await coro
            if doc:
                results.append(doc)
            progress(f"Analyzed module {i + 1}/{len(tasks)}")

        # sort by number of files (largest first)
        results.sort(key=lambda m: -len(m.files))
        return results

    async def _analyze_one_module(
        self,
        name: str,
        files: list[FileInfo],
        project_summary: str,
        project: ProjectContext,
        graph: DependencyGraph | None = None,
    ) -> ModuleDoc | None:
        async with self._sem:
            # Find cross-module dependencies
            cross_module_deps: list[tuple[FileInfo, str]] = []
            if graph:
                cross_module_deps = self._find_cross_module_dependencies(name, files, project.files, graph)

            # Extract signatures for ALL files (no filtering - let LLM decide what's relevant)
            signatures = self._extract_file_signatures(files)

            # Build initial context with signatures and cross-module deps
            initial_context = self._build_exploratory_context(
                name, signatures, cross_module_deps, project_summary
            )

            # Cache key based on content hash of all files
            content_hash_input = "".join(f.content or f.preview or "" for f in files)
            cache_key = f"module:exploring:{name}:{content_hash(content_hash_input)}"

            cached = await self.cache.get(cache_key)
            if cached:
                try:
                    return ModuleDoc(**cached)
                except Exception:
                    pass

            # Exploratory multi-stage analysis
            result = await self._explore_and_document(
                module_name=name,
                initial_context=initial_context,
                all_files=files,
                cross_module_deps=cross_module_deps,
                project=project,
                cache_key=cache_key,
            )

            if result:
                return result

            # Fallback if exploration failed
            return ModuleDoc(name=name, purpose=f"Module containing {len(files)} files")

    def _build_exploratory_context(
        self,
        module_name: str,
        signatures: str,
        cross_deps: list[tuple[FileInfo, str]],
        project_summary: str,
    ) -> str:
        """Build initial context for exploratory module analysis."""
        cross_dep_files = "\n".join([
            f"- **{f.path}** ({f.language}) - imported by {desc}"
            for f, desc in cross_deps
        ]) if cross_deps else "None"

        context = f"""## Task: Explore and Document Module '{module_name}'

## Project Summary
{project_summary}

## Available Files (class/method signatures)
{signatures}

## Cross-Module Dependencies (files from other modules that this module uses)
{cross_dep_files}

## Instructions
You are exploring this module to create comprehensive documentation.

**Workflow** (choose whichever approach works best):
1. Review the signatures above
2. Identify which files contain CORE BUSINESS LOGIC
3. Request the FULL CONTENT of files you need to understand better
4. Once you have enough information, generate the documentation

**File Request Formats** (any of these work):
- "## Files I Need" followed by file paths
- Just list the file names: `com/ijpay/core/IJPayHttpResponse.java`
- Natural language: "Can you show me the content of IJPayHttpResponse.java?"
- Chinese: "请给我看一下 IJPayHttpResponse.java 的代码"

**Documentation Format** (when ready):
```json
{{
  "name": "{module_name}",
  "purpose": "what this module does",
  "description": "how files work together",
  "files": [{{"path": "...", "purpose": "...", "key_symbols": [{{"name": "...", "kind": "...", "line": 1, "description": "..."}}]}}],
  "relationships": [],
  "key_concepts": [{{"name": "...", "explanation": "..."}}]
}}
```

**Important**:
- Prioritize files with business logic (Services, Controllers, Core Models)
- Skip trivial data holders (VO/DTO/Entity with only getters/setters)
- If you already have enough context, you can generate the documentation directly
"""

        return context

    async def _explore_and_document(
        self,
        module_name: str,
        initial_context: str,
        all_files: list[FileInfo],
        cross_module_deps: list[tuple[FileInfo, str]],
        project: ProjectContext,
        cache_key: str,
        max_iterations: int = 5,
    ) -> ModuleDoc | None:
        """Exploratory loop: LLM asks for files until it's ready to document.

        Args:
            module_name: Name of the module
            initial_context: Initial prompt with signatures and instructions
            all_files: All files in the module
            cross_module_deps: Cross-module dependencies
            project: ProjectContext
            cache_key: Cache key for this module analysis
            max_iterations: Maximum number of exploration iterations

        Returns:
            ModuleDoc if successful, None otherwise
        """
        # Normalize paths to forward slash for cross-platform consistency
        # _parse_file_requests normalizes all paths to forward slash, so we must do the same
        def _norm(path: str) -> str:
            return path.replace(chr(92), "/")  # chr(92) is backslash, avoids escape sequence confusion

        path_to_file: dict[str, FileInfo] = {_norm(f.path): f for f in all_files}

        # Combine cross-module deps with all_files for lookup
        all_paths: set[str] = {_norm(f.path) for f in all_files}
        for f, _ in cross_module_deps:
            norm_path = _norm(f.path)
            all_paths.add(norm_path)
            if norm_path not in path_to_file:
                path_to_file[norm_path] = f

        conversation_history = [
            {
                "role": "system",
                "content": "You are a senior engineer exploring a codebase to create detailed documentation. Be thorough but efficient - request only the most important files."
            },
            {
                "role": "user",
                "content": initial_context
            }
        ]

        iteration = 0
        files_provided: set[str] = set()

        while iteration < max_iterations:
            iteration += 1
            logger.debug("Module '%s' exploration iteration %d", module_name, iteration)

            # Get LLM response
            raw = await self._call_llm_with_retry(conversation_history, max_tokens=16384)

            if not raw or not raw.strip():
                logger.warning("Module '%s' empty LLM response at iteration %d", module_name, iteration)
                break

            logger.debug("Module '%s' LLM raw response (first 300 chars): %r", module_name, raw[:300])

            # Check if LLM is ready with final documentation
            if "## Final Documentation" in raw or "```json" in raw:
                # Extract JSON from response
                data = extract_json(raw)
                if data and isinstance(data, dict):
                    data.setdefault("name", module_name)
                    filtered = {k: v for k, v in data.items() if k in ModuleDoc.model_fields}
                    try:
                        doc = ModuleDoc(**filtered)
                        await self.cache.put(cache_key, doc.model_dump())
                        logger.debug("Module '%s' exploration complete after %d iterations", module_name, iteration)
                        return doc
                    except Exception as e:
                        logger.debug("Module '%s' failed to parse ModuleDoc: %s", module_name, e)

            # Parse which files LLM wants
            requested_files = self._parse_file_requests(raw)

            # Check if LLM provided valid documentation even without requesting files
            if not requested_files:
                # Try to extract JSON documentation from the response
                data = extract_json(raw)
                if data and isinstance(data, dict):
                    data.setdefault("name", module_name)
                    filtered = {k: v for k, v in data.items() if k in ModuleDoc.model_fields}
                    try:
                        doc = ModuleDoc(**filtered)
                        await self.cache.put(cache_key, doc.model_dump())
                        logger.info("Module '%s' documented directly from iteration %d", module_name, iteration)
                        return doc
                    except Exception:
                        pass

                # If we've already provided some files, prompt LLM to generate doc
                if files_provided:
                    conversation_history.append({
                        "role": "assistant",
                        "content": raw
                    })
                    # Provide a more directive prompt to generate the documentation
                    conversation_history.append({
                        "role": "user",
                        "content": """Based on the file contents provided above, please generate the module documentation JSON now.
Output your complete ModuleDoc JSON with the format:
```json
{
  "name": "module_name",
  "purpose": "what this module does",
  "description": "how files work together",
  "files": [{"path": "...", "purpose": "...", "key_symbols": [...]}],
  "relationships": [...],
  "key_concepts": [...]
}
```"""
                    })
                    continue  # Continue to next iteration to let LLM generate doc

                # No files provided yet, but we have signatures - provide top files proactively
                if all_files:
                    # Auto-select top 3 important files to show
                    top_files = list(all_files)[:3]
                    file_contents = []
                    for f in top_files:
                        content = f.content if f.content else f.preview
                        if len(content) > 4096:
                            content = content[:4096] + "\n... (truncated)"
                        file_contents.append(f"### {f.path}\n```{f.language}\n{content}\n```")

                    conversation_history.append({
                        "role": "assistant",
                        "content": raw
                    })
                    conversation_history.append({
                        "role": "user",
                        "content": f"""Here are the key files for this module:

{chr(10).join(file_contents)}

Based on these files, please generate the module documentation JSON now."""
                    })
                    continue  # Continue to next iteration

                # True failure: no files, no doc, no context to work with
                logger.warning("Module '%s' no files requested and no valid JSON at iteration %d", module_name, iteration)
                break

            # Filter to only existing files we haven't already provided
            new_files = []
            for path in requested_files:
                if path in files_provided:
                    continue
                if path in path_to_file:
                    new_files.append(path)
                    files_provided.add(path)

            if not new_files:
                logger.debug("Module '%s' all requested files already provided", module_name)
                continue

            # Build file contents for requested files
            file_contents = []
            for path in new_files:
                f = path_to_file.get(path)
                if not f:
                    continue
                content = f.content if f.content else f.preview
                if len(content) > 4096:
                    content = content[:4096] + "\n... (truncated)"
                file_contents.append(f"### {f.path}\n```{f.language}\n{content}\n```")

            files_context = "\n\n".join(file_contents)

            # Add to conversation
            conversation_history.append({
                "role": "assistant",
                "content": raw  # LLM's previous response
            })
            conversation_history.append({
                "role": "user",
                "content": f"""## Requested File Contents
Here are the full contents of the files you requested:

{files_context}

If you need more files, list them now. When you're ready to create the documentation, output your complete ModuleDoc JSON prefixed with "## Final Documentation"."""
            })

        # Max iterations reached or failed
        # This is now informational, not necessarily a failure
        if files_provided:
            logger.info(
                "Module '%s' exploration completed after %d iterations with %d files examined. "
                "Falling back to basic documentation.",
                module_name, iteration, len(files_provided)
            )
        else:
            logger.warning(
                "Module '%s' exploration ended after %d iterations with no files examined",
                module_name, iteration
            )
        return None

    def _parse_file_requests(self, text: str) -> list[str]:
        """Parse file paths from LLM response - accepts multiple formats.

        This method is more lenient than the original implementation:
        1. Explicit "## Files I Need" section (existing)
        2. File paths mentioned naturally in text
        3. Standalone file paths anywhere in the response

        Args:
            text: LLM response text

        Returns:
            List of file paths requested
        """
        import re

        requested = []
        seen = set()

        def add_path(path: str) -> None:
            """Add path if not already seen and looks valid."""
            # Normalize path separators
            path = path.replace("\\", "/")
            path = path.strip()
            if path and path not in seen:
                # Verify it looks like a code file path
                if re.match(r"^[a-zA-Z0-9_\-/.]+(\.[a-zA-Z]+)$", path):
                    seen.add(path)
                    requested.append(path)

        # Pattern for all code file extensions we support
        code_ext_pattern = r"\.(?:java|py|ts|js|tsx|jsx|go|rs|c|cpp|h|hpp|cs|rb|php|swift|kt|scala|lua|dart|vue|svelte|sql|sh|bash)$"

        # 1. Find the "## Files I Need" section (existing format)
        match = re.search(r"## Files I Need\s*\n(.*?)(?:\n##|\Z)", text, re.DOTALL | re.IGNORECASE)
        if match:
            section = match.group(1)
            for line in section.split("\n"):
                line = line.strip()
                # Remove list markers and bold markers
                line = re.sub(r"^[-*•]\s*", "", line).strip()
                line = re.sub(r"\*\*", "", line).strip()
                if not line:
                    continue
                # Match file path pattern
                if re.match(r"^[a-zA-Z0-9_\-/.\\]+" + code_ext_pattern, line, re.IGNORECASE):
                    add_path(line)

        # 2. Find file paths mentioned naturally (common natural language patterns)
        # These patterns indicate the LLM wants to see a specific file
        natural_language_patterns = [
            # English patterns
            r"(?:show|see|look\s*(?:at|into)|read|examine|review|check)\s+(?:me\s+)?(?:the\s+)?(?:content\s+(?:of|for))?\s*([a-zA-Z0-9_\-/.\\]+\.(?:java|py|ts|js|go|rs|c|cpp|h|cs|rb|php|swift|kt|lua|dart|vue|sql|sh))",
            r"(?:could\s+you|can\s+you|please)\s+(?:show|give|send|帮我|我想看|请给我)\s+(?:me\s+)?(?:the\s+)?(?:content\s+(?:of|for))?\s*([a-zA-Z0-9_\-/.\\]+\.(?:java|py|ts|js|go|rs|c|cpp|h|cs|rb|php|swift|kt|lua|dart|vue|sql|sh))",
            # Chinese patterns
            r"(?:帮我|我想看|请给我|查看|看看)\s*(?:一下\s+)?(?:这个\s+)?(?:文件|代码|内容)?\s*[:：]?\s*([a-zA-Z0-9_\-/.\\]+\.(?:java|py|ts|js|go|rs|c|cpp|h|cs|rb|php|swift|kt|lua|dart|vue|sql|sh))",
            r"([a-zA-Z0-9_\-/.\\]+\.(?:java|py|ts|js|go|rs|c|cpp|h|cs|rb|php|swift|kt|lua|dart|vue|sql|sh))\s*(?:的\s+)?(?:内容|代码|实现)",
        ]

        for pattern in natural_language_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                add_path(match)

        # 3. Extract all standalone file paths from the entire text
        # This catches any file path that appears as a standalone word/phrase
        standalone_pattern = r"(?<![a-zA-Z0-9_\-/.])([a-zA-Z0-9_\-/.\\]+\.(?:java|py|ts|js|tsx|jsx|go|rs|c|cpp|h|hpp|cs|rb|php|swift|kt|scala|lua|dart|vue|svelte|sql|sh|bash))(?![a-zA-Z0-9_\-/.\\])"
        for match in re.finditer(standalone_pattern, text):
            add_path(match.group(1))

        return requested

    async def _generate_architecture(
        self, project: ProjectContext, key_files: str, tree_hash: str
    ) -> ArchitectureDiagram:
        cache_key = f"arch:{tree_hash}"
        cached = await self.cache.get(cache_key)
        if cached:
            try:
                return ArchitectureDiagram(**cached)
            except Exception:
                pass

        messages = build_architecture_prompt(project.file_tree, key_files, self.language)
        raw = await self._call_llm_with_retry(messages, max_tokens=4096)

        # DEBUG: Log raw response details
        logger.debug("Architecture LLM raw response: length=%d", len(raw) if raw else 0)
        if raw:
            logger.debug("Architecture raw[:150] = %r", raw[:150])
            logger.debug("Architecture raw[-150:] = %r", raw[-150:])

        data = extract_json(raw)

        # DEBUG: Log extract_json result
        if data is None:
            logger.debug("Architecture extract_json returned None")
        elif not isinstance(data, dict):
            logger.debug("Architecture extract_json returned non-dict: %s", type(data))
        else:
            logger.debug("Architecture extract_json success: keys=%s", list(data.keys()))

        if not data or not isinstance(data, dict):
            logger.warning("Failed to parse architecture JSON. Raw response length: %d, full content:\n%s",
                len(raw) if raw else 0, raw if raw else "empty")
            return ArchitectureDiagram()

        filtered = {k: v for k, v in data.items() if k in ArchitectureDiagram.model_fields}
        try:
            arch = ArchitectureDiagram(**filtered)
        except Exception:
            arch = ArchitectureDiagram()
        await self.cache.put(cache_key, arch.model_dump())
        return arch

    async def _generate_reading_guide(
        self,
        project: ProjectContext,
        doc_map: DocMap,
        module_docs: list[ModuleDoc],
        tree_hash: str,
    ) -> ReadingGuide:
        cache_key = f"guide:{tree_hash}"
        cached = await self.cache.get(cache_key)
        if cached:
            try:
                return ReadingGuide(**cached)
            except Exception:
                pass

        # build rankings (top 20 files by importance)
        rankings_parts = []
        for i, f in enumerate(project.files[:20], 1):
            tag = ""
            if f.is_entrypoint:
                tag = " [entrypoint]"
            elif f.is_config:
                tag = " [config]"
            rankings_parts.append(f"{i}. {f.path}{tag} ({f.lines} lines)")
        rankings = "\n".join(rankings_parts)

        module_parts = []
        for m in module_docs:
            module_parts.append(f"- **{m.name}**: {m.purpose}")
        module_summaries = "\n".join(module_parts)

        messages = build_reading_guide_prompt(rankings, module_summaries, self.language)
        raw = await self._call_llm_with_retry(messages, max_tokens=4096)

        # DEBUG: Log raw response details
        logger.debug("ReadingGuide LLM raw response: length=%d", len(raw) if raw else 0)
        if raw:
            logger.debug("ReadingGuide raw[:150] = %r", raw[:150])
            logger.debug("ReadingGuide raw[-150:] = %r", raw[-150:])

        data = extract_json(raw)

        # DEBUG: Log extract_json result
        if data is None:
            logger.debug("ReadingGuide extract_json returned None")
        elif not isinstance(data, dict):
            logger.debug("ReadingGuide extract_json returned non-dict: %s", type(data))
        else:
            logger.debug("ReadingGuide extract_json success: keys=%s", list(data.keys()))

        if not data or not isinstance(data, dict):
            logger.warning("Failed to parse reading guide JSON. Raw response length: %d, full content:\n%s",
                len(raw) if raw else 0, raw if raw else "empty")
            return ReadingGuide()

        filtered = {k: v for k, v in data.items() if k in ReadingGuide.model_fields}
        try:
            guide = ReadingGuide(**filtered)
        except Exception:
            guide = ReadingGuide()
        await self.cache.put(cache_key, guide.model_dump())
        return guide

    # === New hierarchical doc generation methods ===

    async def _generate_doc_map(
        self,
        project: ProjectContext,
        graph: DependencyGraph,
        tree_hash: str,
        progress: Callable[[str], None],
    ) -> DocMap:
        """Phase 1: Generate hierarchical doc map WITHOUT file contents."""
        cache_key = f"docmap:v2:{tree_hash}"
        cached = await self.cache.get(cache_key)
        if cached:
            try:
                return DocMap(**cached)
            except Exception:
                pass

        # Build summary info for prompt (NO file contents)
        module_deps = graph.get_module_dependencies()
        core_files = graph.get_core_files(20)

        structure_summary = _build_structure_summary(
            project.file_tree, module_deps, core_files
        )

        # Retry logic: max 3 attempts, abort if all fail
        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            messages = build_docmap_prompt(structure_summary, self.language)
            raw = await self._call_llm_with_retry(messages, max_tokens=8192)
            data = extract_json(raw)  # extract_json now rejects XML-tagged responses

            if data and isinstance(data, dict):
                # Success - parse into DocMap
                try:
                    # Field name mapping: short JSON names -> model field names
                    categories = [DocCategory(
                        id=c["id"],
                        title=c["title"],
                        description=c.get("description", ""),
                        parent_id=c.get("parent_id", ""),
                        order=c.get("order", 0),
                    ) for c in data.get("categories", [])]

                    docs = [DocItem(
                        id=d["id"],
                        title=d["title"],
                        category_id=d.get("cat", d.get("category_id", d["id"])),
                        purpose=d.get("purpose", ""),
                        related_file_patterns=d.get("files", d.get("related_file_patterns", [])),
                        depends_on=d.get("deps", d.get("depends_on", [])),
                        order=d.get("order", 0),
                    ) for d in data.get("docs", [])]
                except Exception as e:
                    last_error = f"Failed to parse docmap structure: {e}"
                    logger.warning("Docmap attempt %d/%d failed: %s", attempt + 1, max_retries, last_error)
                    continue

                doc_map = DocMap(categories=categories, docs=docs)

                # Normalize IDs to Chinese if language is "zh" and LLM generated English IDs
                if self.language == "zh":
                    doc_map = self._normalize_ids_to_chinese(doc_map)

                await self.cache.put(cache_key, doc_map.model_dump())
                progress(f"Created doc map with {len(categories)} categories and {len(docs)} docs")
                return doc_map
            else:
                # extract_json returned None - either XML detected or parse failure
                last_error = f"Failed to parse docmap JSON (attempt {attempt + 1}/{max_retries}). Raw length: {len(raw) if raw else 0}, full content:\n{raw if raw else 'empty'}"
                logger.warning(last_error)

        # All retries exhausted - abort generation
        error_msg = f"Docmap generation failed after {max_retries} attempts. Last error: {last_error}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from None

    def _create_default_docmap(self, project: ProjectContext) -> DocMap:
        """Create a default flat docmap when LLM parsing fails."""
        categories = [
            DocCategory(id="overview", title="Overview", description="Project overview", order=0),
            DocCategory(id="modules", title="Modules", description="Code modules", order=1),
        ]

        # Group files by top-level directory
        modules_map = self._group_into_modules(project.files)
        docs = []
        order = 0
        for mod_name, files in modules_map.items():
            doc_id = f"module/{mod_name}"
            docs.append(DocItem(
                id=doc_id,
                title=mod_name.replace("-", " ").replace("_", " ").title(),
                category_id="modules",
                purpose=f"Documentation for {mod_name} module",
                related_file_patterns=[f"{mod_name}/**/*"],
                depends_on=[],
                order=order,
            ))
            order += 1

        return DocMap(categories=categories, docs=docs)

    def _normalize_ids_to_chinese(self, doc_map: DocMap) -> DocMap:
        """Normalize category and doc IDs to Chinese when language is 'zh'.

        This fixes cases where LLM generates English IDs despite Chinese mode being set.
        """
        if self.language != "zh":
            return doc_map

        # Check if IDs are already mostly Chinese (skip normalization if so)
        sample_cat = doc_map.categories[0] if doc_map.categories else None
        sample_doc = doc_map.docs[0] if doc_map.docs else None

        if sample_cat:
            # Check if category IDs contain Chinese characters
            has_chinese_cat = any('\u4e00' <= c <= '\u9fff' for c in sample_cat.id)
            if has_chinese_cat:
                logger.debug("Category IDs already contain Chinese, skipping normalization")
                return doc_map

        if sample_doc:
            has_chinese_doc = any('\u4e00' <= c <= '\u9fff' for c in sample_doc.id)
            if has_chinese_doc:
                logger.debug("Doc IDs already contain Chinese, skipping normalization")
                return doc_map

        # Normalize category IDs
        for cat in doc_map.categories:
            old_id = cat.id
            cat.id = _normalize_doc_id_to_chinese(cat.id, _EN_TO_ZH_CATEGORIES)
            cat.title = _normalize_doc_id_to_chinese(cat.title, _EN_TO_ZH_CATEGORIES)
            if old_id != cat.id:
                logger.info(f"Normalized category ID: '{old_id}' -> '{cat.id}'")

        # Normalize doc IDs and update category_id references
        for doc in doc_map.docs:
            old_id = doc.id
            doc.id = _normalize_doc_id_to_chinese(doc.id, _EN_TO_ZH_CATEGORIES)
            doc.title = _normalize_doc_id_to_chinese(doc.title, _EN_TO_ZH_CATEGORIES)
            # Update category_id if it was also normalized
            doc.category_id = _normalize_doc_id_to_chinese(doc.category_id, _EN_TO_ZH_CATEGORIES)
            if old_id != doc.id:
                logger.info(f"Normalized doc ID: '{old_id}' -> '{doc.id}'")

        return doc_map

    async def _generate_docs_parallel(
        self,
        doc_map: DocMap,
        project: ProjectContext,
        graph: DependencyGraph,
        overview: ProjectOverview | None,
        progress: Callable[[str], None],
        max_retries: int = 2,
    ) -> list[GeneratedDoc]:
        """Phase 3: Generate docs in parallel with semaphore control.
        
        Implements retry mechanism for failed docs:
        1. First pass: attempt all docs in parallel (semaphore-controlled concurrency)
        2. If any failed, retry them up to max_retries times
        3. Continue even if some docs permanently fail (log warning, generate placeholder)
        """
        results: dict[str, GeneratedDoc | None] = {}
        total = len(doc_map.docs)

        # Topological sort by dependencies
        sorted_doc_ids = self._topo_sort_docs(doc_map)

        project_summary = project.name  # overview not available yet, will be refined later

        # Track failed doc ids for retry
        failed_doc_ids: set[str] = set()

        # Prepare doc items and contexts upfront (outside the loop)
        doc_work: list[tuple[str, DocItem, str, str]] = []
        for doc_id in sorted_doc_ids:
            doc_item = doc_map.get_doc(doc_id)
            if not doc_item:
                continue

            # Resume mode: skip docs that are already successfully generated
            if self.generation_mode == "resume":
                status = self.generation_record.get_status(doc_id)
                if status == "success":
                    progress(f"Skipping doc {doc_id} (already generated)")
                    cached_doc = self._get_cached_generated_doc(doc_id, project, graph, doc_map)
                    if cached_doc:
                        results[doc_id] = cached_doc
                    else:
                        # Mark as success but use placeholder - shouldn't happen often
                        results[doc_id] = GeneratedDoc(
                            doc_id=doc_id,
                            content=f"# {doc_item.title}\n\n(Cached from previous run)",
                            referenced_files=[],
                        )
                    continue

            relevant_files = self._get_relevant_files(doc_item, project, graph, doc_map)
            files_context = self._build_files_context(relevant_files)
            deps_context = self._build_dependencies_context(doc_item, doc_map, project)
            doc_work.append((doc_id, doc_item, files_context, deps_context))

        async def generate_one(
            doc_id: str,
            doc_item: DocItem,
            files_context: str,
            deps_context: str,
            retry_failed: bool,
        ) -> tuple[str, GeneratedDoc | None]:
            """Generate a single doc with semaphore control."""
            async with self._sem:  # Use existing semaphore for concurrency control
                progress(f"Generating doc: {doc_id}")

                if not retry_failed:
                    generated = await self._generate_single_doc(
                        doc_item, files_context, project_summary, deps_context
                    )
                    return (doc_id, generated)

                generated = await self._generate_single_doc_with_retry(
                    doc_item, files_context, project_summary, deps_context, max_retries
                )
                return (doc_id, generated)

        # First pass: generate all docs in parallel with semaphore control
        tasks = []
        for doc_id, doc_item, files_context, deps_context in doc_work:
            task = generate_one(doc_id, doc_item, files_context, deps_context, self.retry_failed)
            tasks.append(task)

        # Use asyncio.gather with return_exceptions to handle failures gracefully
        task_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        for result in task_results:
            if isinstance(result, Exception):
                logger.error("Doc generation task raised exception: %s", result)
                continue
            doc_id, generated = result
            if generated is None:
                failed_doc_ids.add(doc_id)
                results[doc_id] = GeneratedDoc(
                    doc_id=doc_id,
                    content=f"# {doc_map.get_doc(doc_id).title if doc_map.get_doc(doc_id) else doc_id}\n\n**Warning: Failed to generate this document after {max_retries} retries.**\n\nThis may be due to LLM errors or invalid responses.",
                    referenced_files=[],
                )
                logger.warning("Doc '%s' failed after %d retries, using placeholder", doc_id, max_retries)
            else:
                results[doc_id] = generated

        # Update generation record for successful docs
        for doc_id, generated in results.items():
            if generated:
                doc_content_hash = content_hash(generated.content)
                self.generation_record.mark_success(doc_id, doc_content_hash)

        # Retry pass: retry failed docs with exponential backoff
        if failed_doc_ids and max_retries > 0 and self.retry_failed:
            retry_count = 0
            while failed_doc_ids and retry_count < max_retries:
                retry_count += 1
                logger.info("Retry pass %d: attempting %d failed docs", retry_count, len(failed_doc_ids))

                # Prepare retry work
                retry_work: list[tuple[str, DocItem, str, str]] = []
                for doc_id in list(failed_doc_ids):
                    doc_item = doc_map.get_doc(doc_id)
                    if not doc_item:
                        continue
                    relevant_files = self._get_relevant_files(doc_item, project, graph, doc_map)
                    files_context = self._build_files_context(relevant_files)
                    deps_context = self._build_dependencies_context(doc_item, doc_map, project)
                    retry_work.append((doc_id, doc_item, files_context, deps_context))

                # Retry in parallel with semaphore control
                retry_tasks = []
                for doc_id, doc_item, files_context, deps_context in retry_work:
                    async def retry_one(doc_id, doc_item, files_context, deps_context):
                        async with self._sem:
                            progress(f"Retry {retry_count}/{max_retries} for doc: {doc_id}")
                            # Clear cache for this doc to force regeneration
                            cache_key = f"doc:v2:{doc_item.id}:{content_hash(files_context[:5000])}"
                            await self.cache.delete(cache_key)
                            return await self._generate_single_doc_with_retry(
                                doc_item, files_context, project_summary, deps_context, max_retries=max_retries
                            )
                    retry_tasks.append(retry_one(doc_id, doc_item, files_context, deps_context))

                still_failing: set[str] = set()
                retry_results = await asyncio.gather(*retry_tasks, return_exceptions=True)

                for i, result in enumerate(retry_results):
                    doc_id = retry_work[i][0]
                    if isinstance(result, Exception):
                        logger.warning("Doc '%s' retry raised exception: %s", doc_id, result)
                        still_failing.add(doc_id)
                        continue
                    generated = result
                    if generated is None:
                        still_failing.add(doc_id)
                        logger.warning("Doc '%s' still failing on retry %d", doc_id, retry_count)
                    else:
                        # Update results with successful retry
                        results[doc_id] = generated
                        doc_content_hash = content_hash(generated.content)
                        self.generation_record.mark_success(doc_id, doc_content_hash)

                failed_doc_ids = still_failing

        if failed_doc_ids:
            logger.warning("After %d retries, %d docs still failed: %s", max_retries, len(failed_doc_ids), failed_doc_ids)

        # Return results in the same order as sorted_doc_ids
        ordered_results = []
        for doc_id in sorted_doc_ids:
            if doc_id in results:
                ordered_results.append(results[doc_id])
            else:
                # Shouldn't happen, but handle gracefully
                doc_item = doc_map.get_doc(doc_id)
                ordered_results.append(GeneratedDoc(
                    doc_id=doc_id,
                    content=f"# {doc_item.title if doc_item else doc_id}\n\n**Warning: Document generation failed.**",
                    referenced_files=[],
                ))

        return ordered_results

    async def _generate_single_doc_with_retry(
        self,
        doc_item: DocItem,
        files_context: str,
        project_summary: str,
        dependencies_context: str,
        max_retries: int = 1,
    ) -> GeneratedDoc | None:
        """Generate a single doc with retry logic. Returns None on permanent failure."""
        for attempt in range(max_retries + 1):
            try:
                result = await self._generate_single_doc(
                    doc_item, files_context, project_summary, dependencies_context
                )
                return result
            except Exception as e:
                if attempt < max_retries:
                    logger.warning("Doc '%s' generation attempt %d failed: %s, retrying...", doc_item.id, attempt + 1, e)
                    await asyncio.sleep(2 ** attempt)  # exponential backoff
                else:
                    logger.error("Doc '%s' permanently failed after %d attempts: %s", doc_item.id, max_retries + 1, e)
                    return None
        return None

    def _topo_sort_docs(self, doc_map: DocMap) -> list[str]:
        """Sort docs by dependencies (docs with no deps first)."""
        in_degree = {d.id: 0 for d in doc_map.docs}
        adj = {d.id: [] for d in doc_map.docs}

        for doc in doc_map.docs:
            for dep in doc.depends_on:
                if dep in in_degree:
                    in_degree[doc.id] += 1
                    adj[dep].append(doc.id)

        queue = [d_id for d_id, deg in in_degree.items() if deg == 0]
        sorted_ids = []

        while queue:
            node = queue.pop(0)
            sorted_ids.append(node)
            for next_node in adj[node]:
                in_degree[next_node] -= 1
                if in_degree[next_node] == 0:
                    queue.append(next_node)

        # Add any remaining (cycles)
        sorted_ids.extend([d.id for d in doc_map.docs if d.id not in sorted_ids])
        return sorted_ids

    def _get_cached_generated_doc(
        self,
        doc_id: str,
        project: ProjectContext,
        graph: DependencyGraph,
        doc_map: DocMap,
    ) -> GeneratedDoc | None:
        """Try to reconstruct a generated doc from cache for resume mode."""
        doc_item = doc_map.get_doc(doc_id)
        if not doc_item:
            return None

        relevant_files = self._get_relevant_files(doc_item, project, graph, doc_map)
        files_context = self._build_files_context(relevant_files)
        cache_key = f"doc:v2:{doc_item.id}:{content_hash(files_context[:5000])}"

        # Try to get from cache
        cached = self._find_cached_doc(cache_key)
        if cached:
            referenced = []
            if "###" in files_context:
                for line in files_context.split("\n"):
                    if line.startswith("### "):
                        referenced.append(line[4:].split(" (")[0])
            return GeneratedDoc(
                doc_id=doc_id,
                content=cached,
                referenced_files=referenced[:15],
            )
        return None

    def _find_cached_doc(self, cache_key: str) -> str | None:
        """Find cached doc content by cache key."""
        import sqlite3
        cache_path = self.cache.db_path if hasattr(self.cache, 'db_path') else None
        if not cache_path:
            return None
        try:
            conn = sqlite3.connect(cache_path)
            cursor = conn.cursor()
            cursor.execute("SELECT data FROM cache WHERE key = ?", (cache_key,))
            row = cursor.fetchone()
            conn.close()
            if row:
                import json
                data = json.loads(row[0])
                return data.get("content", "")
        except Exception:
            pass
        return None

    def _get_relevant_files(
        self,
        doc_item: DocItem,
        project: ProjectContext,
        graph: DependencyGraph,
        doc_map: DocMap,
    ) -> list[FileInfo]:
        """Determine relevant files for a doc using patterns and dependency graph."""
        import fnmatch

        relevant_paths: set[str] = set()

        # 1. Files matching the doc's patterns
        for pattern in doc_item.related_file_patterns:
            for f in project.files:
                if fnmatch.fnmatch(f.path, pattern) or fnmatch.fnmatch(f.path, pattern.replace("/", "\\")):
                    relevant_paths.add(f.path)

        # 2. Add files related to the matched files (dependencies via graph)
        expanded_paths: set[str] = set()
        for path in relevant_paths:
            related = graph.get_related_files(path, max_depth=1)
            expanded_paths.update(related)
        relevant_paths.update(expanded_paths)

        # 3. Add files from dependency docs
        for dep_id in doc_item.depends_on:
            dep_doc = doc_map.get_doc(dep_id)
            if dep_doc:
                for pattern in dep_doc.related_file_patterns:
                    for f in project.files:
                        if fnmatch.fnmatch(f.path, pattern) or fnmatch.fnmatch(f.path, pattern.replace("/", "\\")):
                            relevant_paths.add(f.path)

        # Return as list of FileInfo
        return [f for f in project.files if f.path in relevant_paths]

    def _build_files_context(self, files: list[FileInfo]) -> str:
        """Build context string from file list.

        For pre-chunked files (large files), uses the structural chunks with accurate
        line numbers. For small files, uses the full content with line range annotation.
        """
        if not files:
            return "No relevant files found."

        parts = []
        for f in files:
            if f.is_chunked and f.chunks:
                # Large file with pre-split chunks - each chunk has precise line numbers
                for chunk in f.chunks:
                    parts.append(
                        f"### {f.path} - {chunk.chunk_name} "
                        f"[lines:{chunk.start_line}-{chunk.end_line}]\n"
                        f"```{f.language}\n{chunk.content}\n```"
                    )
            else:
                # Small file - use full content with line range annotation
                content = f.content if f.content else f.preview
                parts.append(
                    f"### {f.path} ({f.language}) [lines:1-{f.lines}]\n"
                    f"```{f.language}\n{content}\n```"
                )
        return "\n\n".join(parts)

    def _build_dependencies_context(
        self,
        doc_item: DocItem,
        doc_map: DocMap,
        project: ProjectContext,
    ) -> str:
        """Build context about dependency docs for a doc."""
        if not doc_item.depends_on:
            return ""

        parts = ["## Dependencies\n"]
        for dep_id in doc_item.depends_on:
            dep_doc = doc_map.get_doc(dep_id)
            if dep_doc:
                parts.append(f"**{dep_doc.title}**: {dep_doc.purpose}")
                parts.append(f"  - Related files: {', '.join(dep_doc.related_file_patterns[:3])}")
                parts.append("")

        return "\n".join(parts)

    def _ensure_source_references(self, content: str, files: list[str]) -> str:
        """Post-process to ensure source references are complete after each section and diagram."""
        import re

        if not content:
            return content

        lines = content.split("\n")
        result_lines = []
        i = 0
        current_section_files = set(files) if files else set()

        while i < len(lines):
            line = lines[i]
            result_lines.append(line)

            # After a Mermaid diagram block, add 图表来源 if missing
            if line.strip() == "```mermaid":
                # Collect the diagram content
                diagram_lines = [line]
                j = i + 1
                while j < len(lines) and not lines[j].strip().startswith("```"):
                    diagram_lines.append(lines[j])
                    j += 1
                if j < len(lines):
                    diagram_lines.append(lines[j])  # closing ```

                # Check if 图表来源 follows this diagram
                # Look ahead to see if next non-empty line is 图表来源
                next_idx = j + 1
                while next_idx < len(lines) and not lines[next_idx].strip():
                    next_idx += 1

                has_source = False
                if next_idx < len(lines):
                    next_line = lines[next_idx].strip()
                    if "**图表来源**" in next_line or "**章节来源**" in next_line:
                        has_source = True

                # If no source reference after diagram, insert one
                if not has_source and files:
                    # Use first file as default source
                    default_source = f"- [{files[0]}](file://{files[0]})"
                    result_lines.append("")
                    result_lines.append("**图表来源**")
                    result_lines.append(default_source)
                    result_lines.append("")

            # After a section header (## or ###), check if 章节来源 follows
            header_match = re.match(r"^(#{2,3})\s+(.+)", line)
            if header_match:
                # Look ahead for 章节来源 or next section header
                next_idx = i + 1
                while next_idx < len(lines) and not lines[next_idx].strip():
                    next_idx += 1

                has_source = False
                if next_idx < len(lines):
                    next_line = lines[next_idx].strip()
                    if "**章节来源**" in next_line:
                        has_source = True

                # If no source reference after section header, insert one
                if not has_source and files:
                    default_source = f"- [{files[0]}](file://{files[0]})"
                    result_lines.append("")
                    result_lines.append("**章节来源**")
                    result_lines.append(default_source)
                    result_lines.append("")

            i += 1

        return "\n".join(result_lines)

    async def _generate_single_doc(
        self,
        doc_item: DocItem,
        files_context: str,
        project_summary: str,
        dependencies_context: str,
    ) -> GeneratedDoc | None:
        """Generate content for a single doc. Returns None on failure."""
        try:
            cache_key = f"doc:v2:{doc_item.id}:{content_hash(files_context[:5000])}"
            cached = await self.cache.get(cache_key)
            if cached:
                try:
                    return GeneratedDoc(**cached)
                except Exception:
                    pass

            messages = build_doc_prompt(
                doc_id=doc_item.id,
                doc_title=doc_item.title,
                doc_purpose=doc_item.purpose,
                files_context=files_context,
                project_summary=project_summary,
                dependencies_context=dependencies_context,
                language=self.language,
            )

            raw = await self._call_llm_with_retry(messages, max_tokens=16384)
            raw_content = raw.strip() if raw else f"# {doc_item.title}\n\n{doc_item.purpose}"

            # Fix JSON-wrapped content: extract if LLM returned {"content": "..."} or {"document": {...}}
            content = extract_json_content(raw_content)
            if content is None:
                content = raw_content
            elif not content.strip().startswith('##'):
                # Extraction worked but content doesn't look like markdown
                # Fall back to raw content
                logger.warning("extract_json_content returned non-markdown for doc '%s', using raw content", doc_item.id)
                content = raw_content

            # Extract referenced files from context
            referenced = []
            if "###" in files_context:
                for line in files_context.split("\n"):
                    if line.startswith("### "):
                        referenced.append(line[4:].split(" (")[0])

            # Post-process: ensure source references are complete
            content = self._ensure_source_references(content, referenced)

            result = GeneratedDoc(
                doc_id=doc_item.id,
                content=content,
                referenced_files=referenced[:15],
            )
            await self.cache.put(cache_key, result.model_dump())
            return result
        except Exception as e:
            logger.error("Failed to generate doc '%s': %s", doc_item.id, e)
            return None

    async def _generate_module_docs_legacy(
        self,
        modules: dict[str, list[FileInfo]],
        project_summary: str,
        project: ProjectContext,
        graph: DependencyGraph,
        progress: Callable[[str], None],
    ) -> list[ModuleDoc]:
        """Phase 4: Legacy module doc generation for backward compatibility."""
        tasks = []
        for name, files in modules.items():
            tasks.append(self._analyze_one_module(name, files, project_summary, project, graph))

        results = []
        for i, coro in enumerate(asyncio.as_completed(tasks)):
            doc = await coro
            if doc:
                results.append(doc)
            progress(f"Generated legacy module {i + 1}/{len(tasks)}")

        # sort by number of files (largest first)
        results.sort(key=lambda m: -len(m.files))
        return results

    def _find_cross_module_dependencies(
        self,
        module_name: str,
        module_files: list[FileInfo],
        all_files: list[FileInfo],
        graph: DependencyGraph,
    ) -> list[tuple[FileInfo, str]]:
        """Find files from OTHER modules that this module's files import.

        Args:
            module_name: Name of the current module
            module_files: Files belonging to this module
            all_files: All project files
            graph: Dependency graph with import info

        Returns:
            List of (FileInfo, description) tuples for cross-module dependencies
        """
        # Build path -> FileInfo lookup (normalize paths to forward slash for cross-platform consistency)
        def _norm(path: str) -> str:
            return path.replace(chr(92), "/")  # chr(92) is backslash, avoids escape sequence confusion

        path_to_file: dict[str, FileInfo] = {_norm(f.path): f for f in all_files}
        module_file_paths: set[str] = {_norm(f.path) for f in module_files}

        cross_deps: list[tuple[FileInfo, str]] = []
        seen_targets: set[str] = set()  # Avoid duplicates

        for f in module_files:
            # Get imports from this file
            imports = graph.get_file_imports(f.path)
            for imp in imports:
                if imp["is_external"]:
                    continue  # Skip external dependencies
                if not imp.get("target_file"):
                    continue
                # Check if target is from a different module
                if imp["target_file"] not in module_file_paths:
                    target_file = path_to_file.get(imp["target_file"])
                    if target_file and target_file.path not in seen_targets:
                        seen_targets.add(target_file.path)
                        cross_deps.append((target_file, f"imported by {_norm(f.path)}"))

        return cross_deps

    def _build_cross_module_context(
        self,
        cross_deps: list[tuple[FileInfo, str]],
    ) -> str:
        """Build context string for cross-module dependencies.

        Args:
            cross_deps: List of (FileInfo, description) tuples

        Returns:
            Formatted context string for LLM prompt
        """
        if not cross_deps:
            return ""

        lines = ["\n\n---\n\n## Cross-Module Dependencies\n"]
        lines.append("The following files from OTHER modules are used by this module:\n\n")

        for file_info, description in cross_deps[:10]:  # Limit to 10 most important
            content = file_info.content if file_info.content else file_info.preview
            if len(content) > 2048:
                content = content[:2048] + "\n... (truncated)"
            lines.append(f"### {file_info.path} ({file_info.language}) - {description}\n```{file_info.language}\n{content}\n```\n")

        return "\n".join(lines)

    # ========== Two-Stage File Selection ==========

    # File patterns that are typically noise (data containers, not business logic)
    _NOISE_PATTERNS = [
        r".*[Vv]o\.java$",      # Value Object
        r".*[Dd]to\.java$",     # Data Transfer Object
        r".*[Pp]o\.java$",      # Persistent Object
        r".*[Ee]ntity\.java$",  # JPA Entity
        r".*[Bb]o\.java$",      # Business Object
        r".*[Cc]onstant.*\.java$",  # Constants only
        r".*Config\.java$",      # Configuration (usually boilerplate)
        r".*Test\.java$",       # Test files
        r".*Exception\.java$",  # Exception classes (often simple)
    ]

    def _auto_filter_noise_files(self, files: list[FileInfo]) -> list[FileInfo]:
        """Remove obvious noise files like VO/DTO/Entity that rarely contain business logic.

        Args:
            files: List of files to filter

        Returns:
            Filtered list with noise files removed
        """
        import re

        noise_patterns = [re.compile(p) for p in self._NOISE_PATTERNS]
        filtered = []
        for f in files:
            # Check if file matches any noise pattern
            is_noise = any(pattern.search(f.path) for pattern in noise_patterns)
            if not is_noise:
                filtered.append(f)
        return filtered

    def _extract_file_signatures(self, files: list[FileInfo]) -> str:
        """Extract class/method signatures from files for lightweight file selection.

        Args:
            files: List of files to extract signatures from

        Returns:
            Formatted string with file signatures
        """
        import re

        lines = ["## File Signatures\n"]
        for f in files:
            content = f.content if f.content else f.preview
            if not content:
                continue

            file_sigs = []
            lang = f.language

            # Java class/method signatures
            if lang == "java":
                # Class declarations
                class_pattern = r"(public|private|protected|abstract|final)?\s*(class|interface|enum)\s+(\w+)"
                for m in re.finditer(class_pattern, content):
                    file_sigs.append(f"  {m.group(0)}")

                # Method signatures (simplified pattern)
                method_pattern = r"(public|private|protected)\s+(static\s+)?(\w+\s)+(\w+)\s*\([^)]*\)"
                for m in re.finditer(method_pattern, content):
                    method_name = m.group(4)
                    # Skip obvious getters/setters
                    if not method_name.startswith("get") and not method_name.startswith("set") and not method_name.startswith("is"):
                        file_sigs.append(f"  {m.group(0)};")

            # Python function signatures
            elif lang == "python":
                func_pattern = r"^(async\s+)?def\s+(\w+)\s*\([^)]*\)"
                for m in re.finditer(func_pattern, content, re.MULTILINE):
                    file_sigs.append(f"  {m.group(0)}")

                class_pattern = r"^class\s+(\w+)"
                for m in re.finditer(class_pattern, content, re.MULTILINE):
                    file_sigs.append(f"  {m.group(0)}")

            # JavaScript/TypeScript
            elif lang in ("javascript", "typescript"):
                func_pattern = r"(function\s+(\w+)|const\s+(\w+)\s*=|(\w+)\s*\([^)]*\)\s*{)"
                for m in re.finditer(func_pattern, content):
                    file_sigs.append(f"  {m.group(0)}")

            # Go
            elif lang == "go":
                func_pattern = r"func\s+(\w+)\s*\([^)]*\)"
                for m in re.finditer(func_pattern, content):
                    file_sigs.append(f"  {m.group(0)}")

            # Only include if we found signatures
            if file_sigs:
                lines.append(f"### {f.path}\n")
                lines.extend(file_sigs[:20])  # Limit to 20 signatures per file
                lines.append("")

        return "\n".join(lines)

    async def _select_priority_files(
        self,
        module_name: str,
        signatures: str,
        cross_deps: list[tuple[FileInfo, str]],
        project_summary: str,
        language: str,
    ) -> dict:
        """Use LLM to select which files are most important for documentation.

        Args:
            module_name: Name of the module
            signatures: File signatures from _extract_file_signatures
            cross_deps: Cross-module dependencies available
            project_summary: Brief project description
            language: Output language

        Returns:
            Dict with 'priority_files' (list of file paths) and 'focus_areas' (list of strings)
        """
        # Build list of cross-module files available
        cross_dep_files = "\n".join([
            f"- {f.path} (from other module, imported by {desc})"
            for f, desc in cross_deps
        ])

        prompt = f"""Analyze the following module '{module_name}' and select the most important files for documentation.

## Project Summary
{project_summary}

## Module File Signatures (classes and methods in each file)
{signatures}

## Cross-Module Dependencies (available for reference)
{cross_dep_files if cross_dep_files else "None"}

## Task
Select the TOP 5-8 most important files that contain CORE BUSINESS LOGIC.
- Skip files that are just data containers (VO/DTO/Entity with no logic)
- Focus on files with complex logic, services, controllers, core models
- Include files that other modules depend on
- If a cross-module file is critical for understanding this module, include it

## Output Format (JSON only)
{{
  "priority_files": ["file1.java", "file2.java"],
  "skip_patterns": ["*VO.java", "*DTO.java"],
  "focus_areas": ["支付流程", "回调处理"]
}}}}"""

        messages = [
            {
                "role": "system",
                "content": "You are a senior engineer selecting important files for documentation."
            },
            {
                "role": "user",
                "content": prompt}
        ]

        raw = await self._call_llm_with_retry(messages, max_tokens=1024)
        data = extract_json(raw)

        if data and isinstance(data, dict):
            return {
                "priority_files": data.get("priority_files", []),
                "skip_patterns": data.get("skip_patterns", []),
                "focus_areas": data.get("focus_areas", [])
            }

        # Fallback: return empty dict (caller will use all files)
        return {}
