"""assemble wiki pages from analysis results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from repowiki.core.graph import DependencyGraph
from repowiki.core.metadata_builder import MetadataBuilder
from repowiki.core.models import (
    DocCategory,
    DocItem,
    DocMap,
    GeneratedDoc,
    ProjectContext,
    WikiData,
)


@dataclass
class WikiPage:
    id: str
    title: str
    content: str
    parent_id: str = ""
    order: int = 0


@dataclass
class SidebarItem:
    title: str
    page_id: str
    children: list[SidebarItem] = field(default_factory=list)


@dataclass
class Wiki:
    pages: list[WikiPage] = field(default_factory=list)
    sidebar: list[SidebarItem] = field(default_factory=list)
    project_name: str = ""
    metadata_builder: Optional[MetadataBuilder] = None

    def get_page(self, page_id: str) -> WikiPage | None:
        for p in self.pages:
            if p.id == page_id:
                return p
        return None

    def get_metadata_builder(self, project_name: str = "") -> MetadataBuilder:
        """Get or create MetadataBuilder for this wiki."""
        if self.metadata_builder is None:
            self.metadata_builder = MetadataBuilder(project_name or self.project_name)
        return self.metadata_builder


class WikiBuilder:
    """constructs a Wiki from analysis results."""

    def build(
        self,
        project: ProjectContext,
        wiki_data: WikiData,
        graph: DependencyGraph,
    ) -> Wiki:
        """Build wiki - supports both legacy modules and new DocMap hierarchy."""
        pages: list[WikiPage] = []
        sidebar: list[SidebarItem] = []

        # New path: Use doc_map if present
        if wiki_data.doc_map and wiki_data.generated_docs:
            return self._build_from_docmap(
                wiki_data.doc_map,
                wiki_data.generated_docs,
                project,
                wiki_data.overview,
                graph,
            )

        # Legacy path: Fall back to flat module structure
        return self._build_legacy(project, wiki_data, graph)

    def _build_from_docmap(
        self,
        doc_map: DocMap,
        generated_docs: list[GeneratedDoc],
        project: ProjectContext,
        overview,
        graph: DependencyGraph,
    ) -> Wiki:
        """Build wiki from hierarchical DocMap with multi-level categories."""
        pages: list[WikiPage] = []
        sidebar: list[SidebarItem] = []

        # Create MetadataBuilder for Qoder-style metadata
        metadata_builder = MetadataBuilder(project.name)

        # 1. Index page (overview)
        overview_md = self._build_overview_page(overview, project)
        pages.append(WikiPage(id="index", title="Overview", content=overview_md, order=0))
        sidebar.append(SidebarItem(title="Overview", page_id="index"))

        # 2. Build hierarchical category tree + doc pages
        root_cats = [c for c in doc_map.categories if c.parent_id == ""]
        order = 1

        for cat in sorted(root_cats, key=lambda c: c.order):
            cat_sidebar = self._build_category_branch(
                cat, doc_map, generated_docs, pages, order, parent_page_id=f"category/{cat.id}",
                metadata_builder=metadata_builder
            )
            order = len(pages) + 1
            if cat_sidebar and (cat_sidebar.children or any(d.category_id == cat.id for d in doc_map.docs)):
                sidebar.append(cat_sidebar)

        # 3. Dependencies page (always last)
        mermaid = graph.to_mermaid()
        if mermaid:
            dep_md = self._build_dependency_page(graph, mermaid)
            pages.append(WikiPage(id="dependencies", title="Dependencies", content=dep_md, order=100))
            sidebar.append(SidebarItem(title="Dependencies", page_id="dependencies"))

        wiki = Wiki(pages=pages, sidebar=sidebar, project_name=project.name)
        wiki.metadata_builder = metadata_builder
        return wiki

    def _build_category_branch(
        self,
        cat: DocCategory,
        doc_map: DocMap,
        generated_docs: list[GeneratedDoc],
        pages: list[WikiPage],
        order: int,
        parent_page_id: str,
        metadata_builder: MetadataBuilder | None = None,
    ) -> SidebarItem | None:
        """Recursively build a category branch including docs and subcategories."""
        # Create catalog in metadata builder
        if metadata_builder:
            parent_catalog_id = None
            if cat.parent_id:
                # Find parent catalog by matching category id
                for existing_cat in metadata_builder.catalogs:
                    if existing_cat.name == doc_map.get_category(cat.parent_id).title if doc_map.get_category(cat.parent_id) else None:
                        parent_catalog_id = existing_cat.id
                        break
            metadata_builder.get_or_create_catalog(cat.title, parent_catalog_id)

        # Build category index page if there are enough docs (P2 optimization)
        cat_docs = [d for d in doc_map.docs if d.category_id == cat.id]
        if len(cat_docs) >= 3:
            index_content = self._build_category_index_page(cat, cat_docs, generated_docs)
            if index_content:
                index_page_id = f"category/{cat.id}"
                pages.append(WikiPage(
                    id=index_page_id,
                    title=cat.title,
                    content=index_content,
                    parent_id=parent_page_id,
                    order=order,
                ))
                sidebar_item = SidebarItem(
                    title=cat.title,
                    page_id=index_page_id,
                    children=[],
                )
            else:
                sidebar_item = SidebarItem(
                    title=cat.title,
                    page_id="",
                    children=[],
                )
        else:
            # Fewer than 3 docs - no category index page, just a folder header
            sidebar_item = SidebarItem(
                title=cat.title,
                page_id="",
                children=[],
            )

        # Add docs directly under this category
        for doc_item in sorted(cat_docs, key=lambda d: d.order):
            gen_doc = self._find_generated_doc(doc_item.id, generated_docs)
            if gen_doc:
                doc_page_id = f"docs/{doc_item.id}"
                pages.append(WikiPage(
                    id=doc_page_id,
                    title=doc_item.title,
                    content=gen_doc.content,
                    parent_id=f"category/{cat.id}",
                    order=doc_item.order,
                ))
                sidebar_item.children.append(
                    SidebarItem(title=doc_item.title, page_id=doc_page_id)
                )

                # Add wiki item to metadata builder
                if metadata_builder:
                    catalog_id = metadata_builder.get_or_create_catalog(cat.title)
                    item = metadata_builder.create_item(
                        title=doc_item.title,
                        description=doc_item.purpose or doc_item.title,
                        catalog_id=catalog_id,
                    )
                    # Add knowledge relation between category and doc
                    metadata_builder.add_knowledge_relation(
                        source_id=catalog_id,
                        target_id=item.id,
                        relationship_type="PARENT_CHILD",
                    )

        # Recursively add subcategories
        subcats = doc_map.get_child_categories(cat.id)
        for subcat in sorted(subcats, key=lambda c: c.order):
            subcat_sidebar = self._build_category_branch(
                subcat, doc_map, generated_docs, pages, order, parent_page_id=f"category/{cat.id}",
                metadata_builder=metadata_builder
            )
            if subcat_sidebar and subcat_sidebar.children:
                sidebar_item.children.append(subcat_sidebar)
            order = len(pages) + 1

        return sidebar_item if sidebar_item.children or cat_docs else None

    def _find_generated_doc(self, doc_id: str, generated_docs: list[GeneratedDoc]) -> GeneratedDoc | None:
        """Find generated doc by doc_id."""
        return next((g for g in generated_docs if g.doc_id == doc_id), None)

    def _build_category_index_page(
        self,
        cat: DocCategory,
        docs: list[DocItem],
        generated_docs: list[GeneratedDoc],
    ) -> str:
        """Build a category index page summarizing child docs with Qoder-style structure."""
        lines = [f"# {cat.title}\n"]

        if cat.description:
            lines.append(f"{cat.description}\n\n")

        # Qoder-style cite block for category overview
        lines.append("<cite>\n")
        lines.append(f"**分类文档: {cat.title}**\n")
        lines.append(f"- 包含 {len(docs)} 个文档\n")
        lines.append("</cite>\n")

        # TOC - Table of Contents
        lines.append("## 目录\n")
        for i, doc_item in enumerate(sorted(docs, key=lambda d: d.order), 1):
            lines.append(f"{i}. [{doc_item.title}](#{doc_item.id})")
        lines.append("")

        # Documents section with status
        lines.append("## 文档列表\n")
        for doc_item in sorted(docs, key=lambda d: d.order):
            gen_doc = self._find_generated_doc(doc_item.id, generated_docs)
            status = "✓" if gen_doc else "○"
            lines.append(f"- [{status}] [{doc_item.title}](docs/{doc_item.id}) — {doc_item.purpose}")

        return "\n".join(lines)

    def _build_legacy(
        self,
        project: ProjectContext,
        wiki_data: WikiData,
        graph: DependencyGraph,
    ) -> Wiki:
        """Build wiki using legacy flat module structure."""
        pages: list[WikiPage] = []
        sidebar: list[SidebarItem] = []

        # 1. index / overview page
        overview = wiki_data.overview
        overview_md = self._build_overview_page(overview, project)
        pages.append(WikiPage(id="index", title="Overview", content=overview_md, order=0))
        sidebar.append(SidebarItem(title="Overview", page_id="index"))

        # 2. architecture page
        arch = wiki_data.architecture
        if arch.architecture_type:
            arch_md = self._build_architecture_page(arch)
            pages.append(WikiPage(id="architecture", title="Architecture", content=arch_md, order=1))
            sidebar.append(SidebarItem(title="Architecture", page_id="architecture"))

        # 3. module pages
        module_sidebar = SidebarItem(title="Modules", page_id="", children=[])
        for i, mod in enumerate(wiki_data.modules):
            mod_id = f"modules/{mod.name}"
            mod_md = self._build_module_page(mod)
            pages.append(WikiPage(
                id=mod_id, title=mod.name, content=mod_md,
                parent_id="modules", order=i,
            ))
            module_sidebar.children.append(SidebarItem(title=mod.name, page_id=mod_id))
        if module_sidebar.children:
            sidebar.append(module_sidebar)

        # 4. reading guide
        guide = wiki_data.reading_guide
        if guide.steps:
            guide_md = self._build_reading_guide_page(guide)
            pages.append(WikiPage(id="reading-guide", title="Reading Guide", content=guide_md, order=10))
            sidebar.append(SidebarItem(title="Reading Guide", page_id="reading-guide"))

        # 5. dependency graph
        mermaid = graph.to_mermaid()
        if mermaid:
            dep_md = self._build_dependency_page(graph, mermaid)
            pages.append(WikiPage(id="dependencies", title="Dependencies", content=dep_md, order=11))
            sidebar.append(SidebarItem(title="Dependencies", page_id="dependencies"))

        return Wiki(pages=pages, sidebar=sidebar, project_name=project.name)

    def _build_overview_page(self, overview, project) -> str:
        lines = [f"# {overview.name or project.name}\n"]

        # Qoder-style <cite> block with key files from entry points and tech stack
        key_files = self._collect_overview_cite_files(overview, project)
        if key_files:
            lines.append("<cite>\n")
            lines.append("**本文引用的文件**\n")
            for f in key_files:
                lines.append(f"- [{f}](file://{f})")
            lines.append("</cite>\n")

        if overview.one_liner:
            lines.append(f"> {overview.one_liner}\n")
        if overview.description:
            lines.append(f"{overview.description}\n")

        # TOC - Table of Contents
        lines.append("## 目录\n")
        toc_items = []
        if overview.project_type:
            toc_items.append("项目类型")
        if overview.entry_points:
            toc_items.append("入口点")
        if overview.tech_stack:
            toc_items.append("技术栈")
        if overview.key_features:
            toc_items.append("主要特性")
        if overview.setup_instructions:
            toc_items.append("快速开始")
        for i, item in enumerate(toc_items, 1):
            lines.append(f"{i}. [{item}](#{item})")
        lines.append("")

        if overview.project_type:
            lines.append(f"**Project Type:** {overview.project_type}\n")

        if overview.entry_points:
            lines.append("**Entry Points:** " + ", ".join(f"`{e}`" for e in overview.entry_points) + "\n")

        if overview.tech_stack:
            lines.append("\n## Tech Stack\n")
            for t in overview.tech_stack:
                ver = f" {t.version}" if t.version else ""
                cat = f" ({t.category})" if t.category else ""
                lines.append(f"- **{t.name}**{ver}{cat}")
            lines.append("")

        if overview.key_features:
            lines.append("\n## Key Features\n")
            for feat in overview.key_features:
                lines.append(f"- {feat}")
            lines.append("")

        if overview.setup_instructions:
            lines.append("\n## Getting Started\n")
            for i, step in enumerate(overview.setup_instructions, 1):
                lines.append(f"{i}. {step}")
            lines.append("")

        return "\n".join(lines)

    def _collect_overview_cite_files(self, overview, project) -> list[str]:
        """Collect key files for the overview <cite> block."""
        files = []
        # Add entry points
        for ep in overview.entry_points[:5]:
            if ep not in files:
                files.append(ep)
        # Add key files from project
        for f in project.files[:20]:
            if f.is_entrypoint or f.is_config:
                if f.path not in files:
                    files.append(f.path)
        return files[:15]

    def _build_architecture_page(self, arch) -> str:
        lines = ["# Architecture\n"]

        # Qoder-style <cite> block with key architecture files
        arch_files = []
        for c in arch.components:
            for f in c.files:
                if f not in arch_files:
                    arch_files.append(f)
        if arch_files:
            lines.append("<cite>\n")
            lines.append("**本文引用的文件**\n")
            for f in arch_files[:15]:
                lines.append(f"- [{f}](file://{f})")
            lines.append("</cite>\n")

        if arch.architecture_type:
            lines.append(f"**Type:** {arch.architecture_type}\n")
        if arch.description:
            lines.append(f"{arch.description}\n")

        # If both component and sequence diagrams exist, use combined view
        if arch.mermaid_component and arch.mermaid_sequence:
            combined_md = self._build_combined_architecture_page(arch)
            lines.append(combined_md)
        else:
            # Legacy separate diagrams
            if arch.mermaid_component:
                lines.append("## Component Diagram\n")
                lines.append(f"```mermaid\n{arch.mermaid_component}\n```\n")
                # Qoder-style 图表来源
                if arch_files:
                    lines.append("**图表来源**\n")
                    for f in arch_files[:5]:
                        lines.append(f"- [{f}](file://{f})")
                    lines.append("")

            if arch.components:
                lines.append("## Components\n")
                for c in arch.components:
                    lines.append(f"### {c.name}\n")
                    if c.purpose:
                        lines.append(f"{c.purpose}\n")
                    if c.files:
                        lines.append("Files: " + ", ".join(f"`{f}`" for f in c.files) + "\n")

            if arch.mermaid_sequence:
                lines.append("## Sequence Diagram\n")
                lines.append(f"```mermaid\n{arch.mermaid_sequence}\n```\n")
                # Qoder-style 图表来源 for sequence diagram
                if arch_files:
                    lines.append("**图表来源**\n")
                    for f in arch_files[:5]:
                        lines.append(f"- [{f}](file://{f})")
                    lines.append("")

        if arch.data_flow:
            lines.append("## Data Flow\n")
            lines.append(f"{arch.data_flow}\n")

        return "\n".join(lines)

    def _build_combined_architecture_page(self, arch) -> str:
        """Build combined architecture page with component + sequence diagrams."""
        lines = []

        # Build a combined sequence diagram that shows both components and flow
        if arch.mermaid_component and arch.mermaid_sequence:
            lines.append("## Combined Architecture\n")
            lines.append("```mermaid\n")
            # Add component diagram interpretation
            lines.append("flowchart TB\n")
            # Extract component names from component diagram
            for c in arch.components:
                lines.append(f"    {c.name.replace(' ', '_')}[\"{c.name}\"]")
            lines.append("```\n")

        if arch.components:
            lines.append("## Components\n")
            for c in arch.components:
                lines.append(f"### {c.name}\n")
                if c.purpose:
                    lines.append(f"{c.purpose}\n")
                if c.files:
                    lines.append("Files: " + ", ".join(f"`{f}`" for f in c.files) + "\n")

        return "\n".join(lines)

    def _build_module_page(self, mod) -> str:
        lines = [f"# {mod.name}\n"]

        # Qoder-style <cite> block with key files from this module
        if mod.files:
            lines.append("<cite>\n")
            lines.append("**本文引用的文件**\n")
            for f in mod.files[:10]:
                lines.append(f"- [{f.path}](file://{f.path})")
            lines.append("</cite>\n")

        if mod.purpose:
            lines.append(f"> {mod.purpose}\n")
        if mod.description:
            lines.append(f"{mod.description}\n")

        if mod.files:
            lines.append("## Files\n")
            for f in mod.files:
                lines.append(f"### `{f.path}`\n")
                if f.purpose:
                    lines.append(f"{f.purpose}\n")
                if f.key_symbols:
                    lines.append("**Key Symbols:**\n")
                    for s in f.key_symbols:
                        line_ref = f" (line {s.line})" if s.line > 0 else ""
                        desc = f" — {s.description}" if s.description else ""
                        lines.append(f"- `{s.name}` ({s.kind}){line_ref}{desc}")
                    lines.append("")

            # Qoder-style 章节来源 - collect all unique file:line references
            source_refs = []
            for f in mod.files[:10]:
                if f.key_symbols:
                    for s in f.key_symbols:
                        if s.line > 0:
                            source_refs.append((f.path, s.line, s.line))
                        else:
                            source_refs.append((f.path, None, None))
                else:
                    source_refs.append((f.path, None, None))

            # Deduplicate while preserving order
            seen = set()
            unique_refs = []
            for path, start, end in source_refs:
                key = (path, start, end)
                if key not in seen:
                    seen.add(key)
                    unique_refs.append((path, start, end))

            for path, start, end in unique_refs:
                if start is not None and end is not None:
                    lines.append(f"- [{path}:{start}-{end}](file://{path}#{start}-{end})")
                else:
                    lines.append(f"- [{path}](file://{path})")
            lines.append("")

        if mod.key_concepts:
            lines.append("## Key Concepts\n")
            for c in mod.key_concepts:
                lines.append(f"- **{c.name}**: {c.explanation}")
            lines.append("")

        if mod.relationships:
            lines.append("## Internal Relationships\n")
            for r in mod.relationships:
                lines.append(f"- `{r.source}` → `{r.target}`: {r.description}")
            lines.append("")

        return "\n".join(lines)

    def _build_reading_guide_page(self, guide) -> str:
        lines = ["# Reading Guide\n"]
        if guide.introduction:
            lines.append(f"{guide.introduction}\n")

        for step in guide.steps:
            time_est = f" (~{step.time_estimate})" if step.time_estimate else ""
            lines.append(f"## Step {step.order}: {step.title}{time_est}\n")
            if step.files:
                lines.append("**Files:** " + ", ".join(f"`{f}`" for f in step.files) + "\n")
            if step.explanation:
                lines.append(f"{step.explanation}\n")

            # Qoder-style 章节来源 for this step
            if step.files:
                lines.append("**章节来源**\n")
                for f in step.files:
                    lines.append(f"- [{f}](file://{f})")
                lines.append("")

        if guide.tips:
            lines.append("## Tips\n")
            for tip in guide.tips:
                lines.append(f"- {tip}")
            lines.append("")

        return "\n".join(lines)

    def _build_dependency_page(self, graph: DependencyGraph, mermaid: str) -> str:
        lines = ["# Module Dependencies\n"]
        lines.append("```mermaid\n" + mermaid + "\n```\n")

        # core files
        core = graph.get_core_files(10)
        if core:
            lines.append("## Core Files (by PageRank)\n")
            for i, path in enumerate(core, 1):
                lines.append(f"{i}. `{path}`")
            lines.append("")

        # entry points
        entries = graph.get_entry_points()
        if entries:
            lines.append("## Likely Entry Points\n")
            for e in entries[:10]:
                lines.append(f"- `{e}`")
            lines.append("")

        return "\n".join(lines)
