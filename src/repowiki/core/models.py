"""data models for repowiki analysis pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FileChunk(BaseModel):
    """A pre-split chunk of a large file, preserving structural boundaries."""

    chunk_id: str = ""  # Unique identifier within the file, e.g. "chunk-0", "chunk-1"
    content: str = ""  # The actual content of this chunk
    start_line: int = 0  # 1-indexed start line number
    end_line: int = 0  # 1-indexed end line number
    chunk_type: str = "block"  # Type: "class", "function", "method", "interface", "enum", "block", "tail"
    chunk_name: str = ""  # Structure name, e.g. "PayKit", "getSmPrivateKey"


class FileInfo(BaseModel):
    """metadata about a single file in the project."""

    path: str
    size: int
    language: str = "unknown"
    lines: int = 0
    preview: str = ""
    content: str = ""
    is_config: bool = False
    is_entrypoint: bool = False

    # Pre-split chunks for large files (>4000 chars)
    # Empty list means: (1) file is small and not chunked, OR (2) chunking not yet performed
    is_chunked: bool = False
    chunks: list[FileChunk] = Field(default_factory=list)


class ProjectContext(BaseModel):
    """everything we know about a project before LLM analysis."""

    name: str
    root: str
    files: list[FileInfo] = Field(default_factory=list)
    file_tree: str = ""

    @property
    def total_lines(self) -> int:
        return sum(f.lines for f in self.files)


# --- LLM analysis output models ---


class TechItem(BaseModel):
    name: str
    category: str = ""  # language, framework, database, etc.
    version: str = ""


class ProjectOverview(BaseModel):
    name: str = ""
    one_liner: str = ""
    description: str = ""
    project_type: str = ""  # backend, frontend, cli-tool, library, full-stack, etc.
    entry_points: list[str] = Field(default_factory=list)  # likely entry point files
    tech_stack: list[TechItem] = Field(default_factory=list)
    setup_instructions: list[str] = Field(default_factory=list)
    key_features: list[str] = Field(default_factory=list)


class Symbol(BaseModel):
    name: str
    kind: str = ""  # function, class, variable, constant
    line: int = 0
    description: str = ""


class FileDoc(BaseModel):
    path: str
    purpose: str = ""
    key_symbols: list[Symbol] = Field(default_factory=list)


class Relationship(BaseModel):
    source: str
    target: str
    description: str = ""


class Concept(BaseModel):
    name: str
    explanation: str = ""


class ModuleDoc(BaseModel):
    name: str
    purpose: str = ""
    description: str = ""
    files: list[FileDoc] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    key_concepts: list[Concept] = Field(default_factory=list)


class Component(BaseModel):
    name: str
    purpose: str = ""
    files: list[str] = Field(default_factory=list)


class ArchitectureDiagram(BaseModel):
    architecture_type: str = ""  # monolith, client-server, microservices, etc.
    description: str = ""
    components: list[Component] = Field(default_factory=list)
    mermaid_component: str = ""
    mermaid_sequence: str = ""
    data_flow: str = ""


class ReadingStep(BaseModel):
    order: int
    title: str
    files: list[str] = Field(default_factory=list)
    explanation: str = ""
    time_estimate: str = ""


class ReadingGuide(BaseModel):
    introduction: str = ""
    steps: list[ReadingStep] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)


# --- Hierarchical doc generation models (must be before WikiData) ---


class DocItem(BaseModel):
    """A single document in the wiki hierarchy."""

    id: str  # URL-safe slug, e.g. "getting-started/installation"
    title: str
    category_id: str  # Parent category slug
    purpose: str = ""  # One-liner explaining this doc
    related_file_patterns: list[str] = Field(default_factory=list)  # Glob patterns, e.g. ["src/auth/*.py", "config/*.py"]
    depends_on: list[str] = Field(default_factory=list)  # Other DocItem IDs this doc needs to understand first
    order: int = 0


class DocCategory(BaseModel):
    """A grouping category for docs (can be nested)."""

    id: str  # URL-safe slug, e.g. "architecture", "api-reference"
    title: str
    description: str = ""
    parent_id: str = ""  # Parent category ID (empty for root-level)
    order: int = 0


class DocMap(BaseModel):
    """Complete document map - defines hierarchy before content is generated."""

    categories: list[DocCategory] = Field(default_factory=list)
    docs: list[DocItem] = Field(default_factory=list)
    root_category_id: str = "root"

    def get_doc(self, doc_id: str) -> DocItem | None:
        return next((d for d in self.docs if d.id == doc_id), None)

    def get_category(self, cat_id: str) -> DocCategory | None:
        return next((c for c in self.categories if c.id == cat_id), None)

    def get_docs_in_category(self, cat_id: str) -> list[DocItem]:
        """Get all docs directly in a category (excluding subcategories)."""
        return [d for d in self.docs if d.category_id == cat_id]

    def get_child_categories(self, parent_id: str) -> list[DocCategory]:
        """Get direct child categories of a category."""
        return [c for c in self.categories if c.parent_id == parent_id]


class GeneratedDoc(BaseModel):
    """Content for a single generated doc."""

    doc_id: str
    content: str = ""
    referenced_files: list[str] = Field(default_factory=list)  # Files actually used (for cite block)


class DocStatus(BaseModel):
    """Tracks the generation status of a single doc."""

    doc_id: str
    status: str = "pending"  # "pending", "success", "failed"
    content_hash: str = ""  # MD5 hash of generated content
    error_message: str = ""  # Error message if failed
    retry_count: int = 0  # Number of retry attempts


class DocGenerationRecord(BaseModel):
    """Tracks the generation status of all docs in a docmap."""

    docmap_hash: str = ""  # Hash of the docmap structure
    docs: dict[str, DocStatus] = Field(default_factory=dict)  # doc_id -> DocStatus

    def get_status(self, doc_id: str) -> str:
        """Get status for a doc, returns 'pending' if not found."""
        return self.docs.get(doc_id, DocStatus(doc_id=doc_id, status="pending")).status

    def mark_success(self, doc_id: str, content_hash: str) -> None:
        """Mark a doc as successfully generated."""
        self.docs[doc_id] = DocStatus(doc_id=doc_id, status="success", content_hash=content_hash)

    def mark_failed(self, doc_id: str, error_message: str, retry_count: int = 0) -> None:
        """Mark a doc as failed."""
        self.docs[doc_id] = DocStatus(doc_id=doc_id, status="failed", error_message=error_message, retry_count=retry_count)

    def get_pending_docs(self) -> list[str]:
        """Get list of doc_ids that are pending or failed."""
        return [doc_id for doc_id, status in self.docs.items() if status.status in ("pending", "failed")]

    def get_successful_docs(self) -> list[str]:
        """Get list of doc_ids that were successfully generated."""
        return [doc_id for doc_id, status in self.docs.items() if status.status == "success"]


# --- WikiData (uses models defined above) ---


class WikiData(BaseModel):
    """complete wiki analysis output."""

    overview: ProjectOverview = Field(default_factory=ProjectOverview)
    modules: list[ModuleDoc] = Field(default_factory=list)
    architecture: ArchitectureDiagram = Field(default_factory=ArchitectureDiagram)
    reading_guide: ReadingGuide = Field(default_factory=ReadingGuide)
    file_index: dict[str, FileDoc] = Field(default_factory=dict)
    # New hierarchical doc generation fields
    doc_map: DocMap = Field(default_factory=DocMap)
    generated_docs: list[GeneratedDoc] = Field(default_factory=list)
