"""prompt templates for repowiki analysis pipeline."""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# ============================================================================
# COMMON CONSTANTS (extracted to eliminate redundancy)
# ============================================================================

INSTRUCTIONS = {
    "no_filler": (
        "Be direct and specific. No filler phrases like 'leveraging', 'utilizing', "
        "'cutting-edge', 'robust', or 'comprehensive'. Just describe what things do."
    ),
    "json_only": (
        "Output ONLY valid JSON. No markdown fences, no explanation text before or after. "
        "Just the JSON object/array."
    ),
    "source_ref": (
        "After each major claim, include source reference using format: "
        "[filename.ext:startLine-endLine](file://filename.ext#startLine-endLine)"
    ),
}

LANG_TEMPLATES = {
    "en": {
        "respond": "Respond in English.",
        "translate_all": "Write all content in English.",
        "name": "English",
        # Doc structure labels
        "cite_block_title": "Files Referenced",
        "toc_title": "Table of Contents",
        "diagram_source": "Diagram Source",
        "section_source": "Section Source",
        "troubleshooting": "Troubleshooting",
        "final_sources": "Sources",
        "cite_block": "**Files Referenced**\n",
        "toc": "## Table of Contents\n",
        "diagram_src": "**Diagram Source**",
        "section_src": "**Section Source**",
        "trouble": "## Troubleshooting\n",
        "final_src": "## Sources\n",
        "example_filename": "filename",
    },
    "zh": {
        "respond": "请用中文回答。",
        "translate_all": "将所有内容翻译成中文后再输出。",
        "name": "中文",
        # Doc structure labels
        "cite_block_title": "本文引用的文件",
        "toc_title": "目录",
        "diagram_source": "图表来源",
        "section_source": "章节来源",
        "troubleshooting": "故障排查指南",
        "final_sources": "章节来源",
        "cite_block": "**本文引用的文件**\n",
        "toc": "## 目录\n",
        "diagram_src": "**图表来源**",
        "section_src": "**章节来源**",
        "trouble": "## 故障排查指南\n",
        "final_src": "## 章节来源\n",
        "example_filename": "文件名",
    },
}

# ============================================================================
# JSON OUTPUT SCHEMAS (reusable templates)
# ============================================================================

SCHEMA_OVERVIEW = """{
  "name": "project name",
  "one_liner": "what this project does in one sentence (max 20 words)",
  "description": "2-3 paragraphs explaining the project in plain language",
  "project_type": "one of: backend-app, frontend-app, cli-tool, library, full-stack, monorepo, or unknown",
  "entry_points": ["main.py", "app.py"],
  "tech_stack": [{"name": "Python", "category": "language", "version": "3.10+"}],
  "setup_instructions": ["step 1", "step 2"],
  "key_features": ["feature 1", "feature 2"]
}"""

SCHEMA_MODULE = """{{
  "name": "{module_name}",
  "purpose": "one sentence describing what this module does",
  "description": "2-3 sentences explaining the module purpose and how files work together",
  "files": [
    {{
      "path": "relative/path/to/file.py",
      "purpose": "what this specific file does",
      "key_symbols": [
        {{"name": "ClassName or function_name", "kind": "class|function|method|variable|constant", "line": 42, "description": "1-2 sentences: what it does and why it matters"}}
      ]
    }}
  ],
  "relationships": [{{"source": "file_a.py", "target": "file_b.py", "description": "how they interact"}}],
  "key_concepts": [{{"name": "concept name", "explanation": "why this matters"}}]
}}"""

SCHEMA_ARCHITECTURE = """{
  "architecture_type": "one of: monolith, layered, mvc, client-server, microservices, event-driven, plugin-system, pipeline, or library",
  "description": "2-3 sentences explaining WHY this architecture was chosen and how components interact",
  "components": [
    {"name": "ComponentName", "purpose": "what this component does and why it exists", "files": ["file1.py", "file2.py"]}
  ],
  "mermaid_component": "graph TD\\n  A[Component] --> B[Component]\\n  ...",
  "mermaid_sequence": "sequenceDiagram\\n  participant A\\n  A->>B: request\\n  ...",
  "data_flow": "2-3 sentences describing how data moves through the system"
}"""

SCHEMA_READING_GUIDE = """{
  "introduction": "2-3 sentences on how to approach reading this codebase and what makes it unique",
  "steps": [
    {"order": 1, "title": "step title", "files": ["file1.py", "file2.py"], "explanation": "WHY these files matter - what to look for and how it connects to the bigger picture", "time_estimate": "5 min"},
    {"order": 2, "title": "...", "files": ["..."], "explanation": "WHY this step builds on the previous one and what new concepts it introduces", "time_estimate": "10 min"}
  ],
  "tips": ["general tip 1 for reading this codebase", "general tip 2"]
}"""

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _get_lang(language: str) -> dict:
    """Get language template, fallback to English."""
    return LANG_TEMPLATES.get(language, LANG_TEMPLATES["en"])


# ============================================================================
# PROMPT BUILDERS (Markdown format, no XML tags)
# ============================================================================

def build_overview_prompt(file_tree: str, key_files: str, language: str = "en") -> list[dict]:
    lang = _get_lang(language)

    return [
        {
            "role": "system",
            "content": f"""## System
You are a senior software engineer explaining a project to a new team member.

## Instructions
- {INSTRUCTIONS["no_filler"]}
- Think about the project structure BEFORE generating output. Identify what type of project this is and what the entry points are.
- {lang["respond"]}""",
        },
        {
            "role": "user",
            "content": f"""## Context

### File Tree
```
{file_tree}
```

### Key Files
{key_files}

## Task
Generate a project overview as JSON.

## Output Format
```json
{SCHEMA_OVERVIEW}
```

### Project type detection rules:
- Has package.json + src/ with components/ → frontend-app
- Has requirements.txt/pyproject.toml + app.py/routes/ → backend-app
- Has package.json with bin/ entry → cli-tool
- Has no UI files, mostly library code → library
- Has both frontend AND backend markers → full-stack
- Has multiple packages/workspaces → monorepo

## Constraint
- {INSTRUCTIONS["json_only"]}
- {lang["translate_all"]}""",
        },
    ]


def build_module_prompt(
    module_name: str,
    files_context: str,
    project_summary: str,
    language: str = "en",
) -> list[dict]:
    lang = _get_lang(language)

    return [
        {
            "role": "system",
            "content": f"""## System
You are a senior engineer documenting your own code.

## Instructions
- {INSTRUCTIONS["no_filler"]}
- Explain what each file does, how files relate to each other, and what the key functions/classes are.
- For each key_symbol, you MUST include the actual source code line number where it is defined.
- {lang["respond"]}""",
        },
        {
            "role": "user",
            "content": f"""## Project
{project_summary}

## Task
Document the '{module_name}' module.

## Files
{files_context}

## Output Format
```json
{SCHEMA_MODULE.format(module_name=module_name)}
```

### Requirements:
- For each key_symbol, specify the 'line' number where it appears in the source
- The 'kind' must be one of: class, function, method, variable, constant, decorator
- List only the MOST important symbols per file (max 5 per file)
- Do NOT invent line numbers - only include symbols where you can see the actual line

## Constraint
- {INSTRUCTIONS["json_only"]}
- {lang["translate_all"]}""",
        },
    ]


def build_architecture_prompt(
    file_tree: str,
    key_files: str,
    language: str = "en",
) -> list[dict]:
    lang = _get_lang(language)

    return [
        {
            "role": "system",
            "content": f"""## System
You are a software architect analyzing a codebase.

## Instructions
- {INSTRUCTIONS["no_filler"]}
- Identify the architecture pattern and generate Mermaid diagrams.
- Mermaid syntax must be valid. Use simple node names (no special chars).
- Analyze the actual code structure to identify components, their responsibilities, and how data flows between them.
- {lang["respond"]}""",
        },
        {
            "role": "user",
            "content": f"""## Context

### File Tree
```
{file_tree}
```

### Key Files
{key_files}

## Task
Analyze the architecture thoroughly. Output JSON.

## Output Format
```json
{SCHEMA_ARCHITECTURE}
```

### Architecture type selection:
- monolith: single deployable unit
- layered: presentation/business/data separation
- mvc: models, views, controllers
- client-server: client app vs API server
- microservices: separate services communicating
- event-driven: producers/consumers, message queues
- plugin-system: core + extensions
- pipeline: data sources → transformations → outputs
- library: reusable code, no main entry

### Requirements:
- architecture_type: Choose the BEST match, not just 'monolith'
- Each component needs a 'purpose' that explains WHY it exists
- mermaid_component diagram should show the MAIN components (max 8 nodes)
- mermaid_sequence should show a typical request/response flow
- data_flow should describe how data moves from input to output
- Mermaid code must be a single string with \\n for newlines. Use simple alphanumeric node IDs (no spaces, no special chars).

## Constraint
- {INSTRUCTIONS["json_only"]}
- {lang["translate_all"]}""",
        },
    ]


def build_reading_guide_prompt(
    rankings: str,
    module_summaries: str,
    language: str = "en",
) -> list[dict]:
    lang = _get_lang(language)

    return [
        {
            "role": "system",
            "content": f"""## System
You are a mentor helping a developer understand a new codebase.

## Instructions
- {INSTRUCTIONS["no_filler"]}
- Create a reading guide: which files to read, in what order, and WHY each matters.
- Start from entry points and configuration, then core logic, then utilities.
- Each step should explain WHAT to look for AND WHY this file is important to understand the codebase.
- {lang["respond"]}""",
        },
        {
            "role": "user",
            "content": f"""## Context

### File Importance Rankings
{rankings}

### Module Summaries
{module_summaries}

## Task
Create a reading guide with 5-10 steps. Output JSON.

## Output Format
```json
{SCHEMA_READING_GUIDE}
```

### Requirements:
- Each step's 'explanation' MUST answer: WHY should I read these files? What will I understand after?
- Do NOT just list files - explain the connection between files and what patterns to look for
- Group files logically: entry points together, core logic together, utilities together
- First steps should build mental model, later steps add detail
- time_estimate should be realistic for someone new to the codebase
- tips should cover gotchas, common pitfalls, or key things to notice

## Constraint
- {INSTRUCTIONS["json_only"]}
- {lang["translate_all"]}""",
        },
    ]


def build_chat_prompt(
    question: str,
    context_chunks: str,
    language: str = "en",
) -> list[dict]:
    lang = _get_lang(language)

    return [
        {
            "role": "system",
            "content": f"""## System
You are a knowledgeable developer answering questions about a codebase.

## Instructions
- Answer based on the actual code shown below, not general knowledge.
- Reference specific files and line numbers when relevant.
- Be direct -- answer the question, don't give a lecture.
- {lang["respond"]}""",
        },
        {
            "role": "user",
            "content": f"""## Relevant Code
{context_chunks}

## Question
{question}""",
        },
    ]


def build_docmap_prompt(structure_summary: str, language: str = "en") -> list[dict]:
    """Build doc map prompt - NO file contents, only structure."""
    lang = _get_lang(language)

    # Language-specific aggregation rules (universal, not project-specific)
    lang_aggregation_rules = {
        "en": {
            "aggregation_rule": "Related topics that serve a common purpose or belong to a common domain MUST share a parent category. Never create flat structures where related items are separate root-level categories.",
            "good_example_title": "Good: Related topics grouped under parent",
            "good_example": """categories: [
  {"id": "auth", "title": "Authentication", ...},
  {"id": "auth/login", "title": "Login", "parent_id": "auth", ...},
  {"id": "auth/register", "title": "Registration", "parent_id": "auth", ...},
  {"id": "auth/password-reset", "title": "Password Reset", "parent_id": "auth", ...}
]
IDs: auth/login, auth/register, auth/password-reset""",
            "bad_example_title": "Bad: Related topics as flat root items",
            "bad_example": """categories: [
  {"id": "login", ...},      <- WRONG! Should be under "auth"
  {"id": "register", ...},   <- WRONG! Should be under "auth"
  {"id": "password-reset", ...} <- WRONG! Should be under "auth"
]
IDs: login, register, password-reset""",
            "principle": "Think about DOMAINS and PURPOSES. What topics belong together? What would a user expect to find grouped?",
        },
        "zh": {
            "aggregation_rule": "具有共同目的或属于同一领域的主题必须共享父类别。禁止将相关主题作为独立的顶级类别创建扁平结构。",
            "good_example_title": "正确：相关主题按父类别分组",
            "good_example": """categories: [
  {"id": "认证", "title": "认证", ...},
  {"id": "认证/登录", "title": "登录", "parent_id": "认证", ...},
  {"id": "认证/注册", "title": "注册", "parent_id": "认证", ...},
  {"id": "认证/密码重置", "title": "密码重置", "parent_id": "认证", ...}
]
IDs: 认证/登录, 认证/注册, 认证/密码重置""",
            "bad_example_title": "错误：相关主题作为扁平的顶级项目",
            "bad_example": """categories: [
  {"id": "登录", ...},      <- 错误！应该在"认证"下
  {"id": "注册", ...},      <- 错误！应该在"认证"下
  {"id": "密码重置", ...}  <- 错误！应该在"认证"下
]
IDs: 登录, 注册, 密码重置""",
            "principle": "思考领域和目的。哪些主题应该归为一组？用户会期望在哪里找到它们？",
        },
    }
    lang_defaults = lang_aggregation_rules.get(language, lang_aggregation_rules["en"])

    # Language-specific doc defaults
    lang_doc_defaults = {
        "en": {
            "root_category_example": '{"id": "guide", "title": "Guides", "description": "Usage guides and tutorials", "parent_id": "", "order": 1}',
            "sub_category_example": '{"id": "guide/installation", "title": "Installation", "description": "How to install the project", "parent_id": "guide", "order": 1}',
            "leaf_category_example": '{"id": "guide/installation/windows", "title": "Windows Installation", "description": "Installation on Windows", "parent_id": "guide/installation", "order": 1}',
            "doc_example": '{"id": "guide/installation/windows", "title": "Windows Installation", "cat": "guide/installation/windows", "purpose": "Step-by-step Windows installation guide", "files": ["setup.py", "pyproject.toml"], "deps": [], "order": 1}',
            "id_note": "Category IDs use / separator: 'guide/installation', 'guide/installation/windows'",
            "user_journey": "Organize by USER JOURNEY, not code structure. Categories follow: Getting Started → How-to Guides → API Reference → Integration → Troubleshooting → Architecture",
            "doc_types": "Include practical doc types: 'troubleshooting' (common errors/solutions), 'performance' (optimization tips), 'best-practices' (recommended patterns), 'faq' (frequently asked questions)",
        },
        "zh": {
            "root_category_example": '{"id": "指南", "title": "指南", "description": "使用指南和教程", "parent_id": "", "order": 1}',
            "sub_category_example": '{"id": "指南/安装配置", "title": "安装配置", "description": "项目的安装和配置指南", "parent_id": "指南", "order": 1}',
            "leaf_category_example": '{"id": "指南/安装配置/Windows安装", "title": "Windows安装", "description": "Windows环境安装步骤", "parent_id": "指南/安装配置", "order": 1}',
            "doc_example": '{"id": "指南/安装配置/Windows安装", "title": "Windows安装", "cat": "指南/安装配置/Windows安装", "purpose": "详细的Windows环境安装步骤", "files": ["pom.xml", "build.gradle"], "deps": [], "order": 1}',
            "id_note": "类别ID使用分层路径，例如：'核心架构/核心组件详解'",
            "user_journey": "按用户旅程组织，而非代码结构。分类应遵循：快速开始 → 使用指南 → API参考 → 集成指南 → 故障排查 → 架构说明",
            "doc_types": "包含实用文档类型：'故障排除'（常见错误/解决方案）、'性能优化'（优化技巧）、'最佳实践'（推荐模式）、'常见问题'（FAQ）",
        },
    }
    lang_doc = lang_doc_defaults.get(language, lang_doc_defaults["en"])

    return [
        {
            "role": "system",
            "content": f"""## System
You are a technical writer designing documentation structure.

## Instructions
- Create a deep, logical hierarchy (3-5 levels) that helps readers understand the codebase from overview to details.
- Think about what concepts need to be explained first before others.
- Group related topics together. Use hierarchical category IDs with / separator.
- All titles, descriptions, category IDs, and doc IDs MUST be in the same language as the query.
- {lang["respond"]}""",
        },
        {
            "role": "user",
            "content": f"""## Project Structure
{structure_summary}

## Task
Analyze the project and create a deep documentation hierarchy (3-5 levels).
Structure should go from: overview → categories → subcategories → topics → subtopics.

## Organization Rules

### User Journey Rule
{lang_doc['user_journey']}

### Doc Types
{lang_doc['doc_types']}

### ID Format
{lang_doc['id_note']}

## Output Format

### Categories
- Root category: {lang_doc['root_category_example']}
- Sub category: {lang_doc['sub_category_example']}
- Leaf category: {lang_doc['leaf_category_example']}

### Docs
- Doc example: {lang_doc['doc_example']}

### Schema
```json
{{
  "categories": [...],
  "docs": [...]
}}
```

## Requirements
- Create hierarchical categories: top-level → subcategories → leaf categories (3-5 levels deep)
- Category IDs use / separator: 'architecture/core-components', 'architecture/core-components/paykit'
- Doc IDs should match their leaf category path for proper file placement
- Each doc's cat must match a category's id for proper nesting
- Each doc's files should match the files that doc explains
- deps creates reading order - doc needs understanding of its dependencies first
- files use glob syntax: 'src/auth/*.py', 'config/**/*', '*.json'
- Think: what would a new developer read FIRST to understand this codebase?
- All text must be in the same language as the query

## Granularity
- Each leaf doc should cover ONE specific concept/task, NOT multiple related topics
- If a topic has variations (e.g., database options, cloud providers, API versions), create SEPARATE docs for each
- Target: each doc generates 200-500 lines of content, NOT 800+ lines
- If you find yourself writing 'and also...', 'additionally...', 'another thing...' → split into separate docs

## Aggregation Rule (CRITICAL)
{lang_defaults['aggregation_rule']}
{lang_defaults['principle']}

### {lang_defaults['good_example_title']}
```
{lang_defaults['good_example']}
```

### {lang_defaults['bad_example_title']}
```
{lang_defaults['bad_example']}
```

## Constraint
- {INSTRUCTIONS["json_only"]}""",
        },
    ]


def build_doc_prompt(
    doc_id: str,
    doc_title: str,
    doc_purpose: str,
    files_context: str,
    project_summary: str,
    dependencies_context: str = "",
    language: str = "en",
) -> list[dict]:
    """Build a single doc prompt - Markdown format for complex documentation."""
    lang = _get_lang(language)

    return [
        {
            "role": "system",
            "content": f"""## System
You are a senior engineer writing documentation.

## Instructions
- {INSTRUCTIONS["no_filler"]}
- Explain the concept clearly, with code examples where helpful.
- Reference specific file paths and line numbers when relevant.
- {lang["respond"]}""",
        },
        {
            "role": "user",
            "content": f"""## Metadata
- **DocId**: {doc_id}
- **Title**: {doc_title}
- **Purpose**: {doc_purpose}
- **Project**: {project_summary}

## Dependencies
{dependencies_context if dependencies_context else "(none)"}

## Source Files
{files_context}

## Output Structure

### CiteBlock
Start with a cite block listing ALL files used:
```
{lang['cite_block']}- [{lang['example_filename']}1](file://{lang['example_filename']}1)
- [{lang['example_filename']}2](file://{lang['example_filename']}2)
```

### TableOfContents
Then add a Table of Contents:
```
{lang['toc']}1. [Section1](#section1)
2. [Section2](#section2)
```

### Sections
Write each section with 2-3 DETAILED PARAGRAPHS (not just bullet points):
- Each section must have 2-3 paragraphs of 3-5 sentences each
- Paragraphs should explain the 'why' and 'how', not just state 'what'
- Cover: (1) what problem it solves, (2) how it works, (3) usage patterns, (4) edge cases
- Only diagram-only sections may use structured bullet points instead
- Clear section headers (## Section Name)
- Inline source references after key claims: [filename:line]

### MermaidDiagrams
Include 2-3 different diagram types based on content:
- **flowchart TD** - YES/NO decision trees, conditional logic, process flows
  - Use decision diamonds for choice points
  - Perfect for: "Should I use option A or B?", "Is this feature supported?"
- **sequenceDiagram** - API calls, request/response interactions, call chains
- **classDiagram** - Class relationships, inheritance, interfaces
- **graph TB/LR** - Module dependencies, component hierarchy

After each Mermaid diagram block (before the next ## header), add:
```
{lang['diagram_src']}
- [filename1:line1-line2](file://filename1#line1-line2)
- [filename2:line3-line4](file://filename2#line3-line4)
```

### SectionFooter
After EVERY section (## Section Name) without exception, add:
```
{lang['section_src']}
- [filename:startLine-endLine](file://filename#startLine-endLine)
```

This includes:
- Sections with ONLY a diagram (Mermaid)
- Sections with just one sentence
- Sections with just bullet points
- Subsections like "## Performance Considerations" or "## Conclusion"
- DO NOT skip ANY section, even if it seems minor

Every section MUST end with {lang['section_src']} before the next ## header.

### Troubleshooting
Before final sources section, add:
```
{lang['trouble']}- Issue 1: description of problem → root cause → solution
- Issue 2: description of problem → root cause → solution
- Base these on actual error handling code found in the files
- Each issue should have {lang['diagram_src']} and {lang['section_src']}
```

### FinalSources
End with a complete Sources section:
```
{lang['final_src']}- [filename:start-end](file://filename#start-end)
```

## Format
- Output **pure Markdown**. Do NOT wrap content in JSON, do not use code fences with json.
- Start directly with the cite block, then Table of Contents, then sections.
- Every claim must be traceable to a specific file and line number.

## Translation
- {lang["translate_all"]}""",
        },
    ]


def extract_json_content(text: str) -> str | None:
    """Extract actual content from potential JSON-wrapped LLM responses.

    Handles two formats:
    1. {"content": "..."} - extracts .content field
    2. {"document": {"content": "...", ...}} - extracts .document.content field

    Also handles the case where content is wrapped in ```json code fences.

    Returns:
        The extracted string content, or None if not JSON-wrapped.
    """
    if not text or not text.strip():
        return None

    stripped = text.strip()
    lines = stripped.split('\n')

    # Remove ```json code fence if present
    if lines and lines[0].strip() == '```json':
        lines = lines[1:]
    if lines and lines[-1].strip() == '```':
        lines = lines[:-1]

    json_text = '\n'.join(lines)

    try:
        data = json.loads(json_text)

        # Format 1: {"content": "..."}
        if isinstance(data, dict) and "content" in data:
            return data["content"]

        # Format 2: {"document": {"content": ...}}
        if isinstance(data, dict) and "document" in data:
            doc = data["document"]
            if isinstance(doc, dict) and "content" in doc:
                return doc["content"]

    except json.JSONDecodeError:
        pass

    return None


def _build_structure_summary(
    file_tree: str,
    module_deps: dict[str, set[str]],
    core_files: list[str],
) -> str:
    """Build a summary of project structure for docmap prompt (NO file contents)."""
    lines = []
    lines.append(f"File tree:\n{file_tree[:3000]}")

    if module_deps:
        lines.append("\n## Module Dependencies")
        for mod, deps in sorted(module_deps.items()):
            dep_str = ", ".join(sorted(deps)) if deps else "none"
            lines.append(f"- {mod} → {dep_str}")

    if core_files:
        lines.append("\n## Top Files by Importance (PageRank)")
        for f in core_files[:15]:
            lines.append(f"- {f}")

    return "\n".join(lines)


def build_category_index_prompt(
    category_title: str,
    category_description: str,
    child_docs: list[dict],
    language: str = "en",
) -> list[dict]:
    """Build a category index page prompt summarizing child docs."""
    lang = _get_lang(language)
    child_summaries = "\n".join(
        f"- **{title}**: {purpose}" for title, purpose in child_docs
    )
    return [
        {
            "role": "system",
            "content": f"""## System
You are a senior technical writer creating index pages.

## Instructions
Be concise and helpful. Summarize what each child doc covers.
- {lang["respond"]}""",
        },
        {
            "role": "user",
            "content": f"""## Category
- **Title**: {category_title}
- **Description**: {category_description}

## Child Docs
{child_summaries}

## Task
Write a brief introduction for this category (2-3 sentences) explaining what topics it covers and how the docs relate to each other.""",
        },
    ]


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def extract_json(text: str) -> dict | list | None:
    """Extract JSON from LLM output using robust parsing.

    Uses json.JSONDecoder.raw_decode() which is specifically designed for
    extracting JSON from partial strings with trailing content - the exact
    use case for LLM output parsing.

    Args:
        text: The raw LLM response text.

    Returns:
        Parsed JSON dict/list, or None if parsing fails.
    """
    logger.debug("extract_json called with text length=%d", len(text) if text else 0)

    if not text or not text.strip():
        logger.debug("extract_json: empty text")
        return None

    original_text = text
    text_len = len(text)

    # strip markdown code fences
    text = re.sub(r'^```(?:json)?\s*\n?', '', text.strip(), flags=re.MULTILINE)
    text = re.sub(r'\n?```\s*$', '', text.strip(), flags=re.MULTILINE)
    logger.debug("extract_json: after strip fences, text length=%d", len(text))

    # Strategy 1: Use json.JSONDecoder.raw_decode() - industry standard for LLM output
    # This method parses JSON starting from position 0 and returns (object, end_position)
    # It handles all JSON syntax correctly (strings, escapes, Unicode, etc.)
    # and stops at the first valid JSON, ignoring trailing content
    try:
        decoder = json.JSONDecoder()
        obj, end_pos = decoder.raw_decode(text)
        logger.debug("extract_json: Strategy1 success, end_pos=%d, total_len=%d", end_pos, len(text))
        if end_pos < len(text):
            logger.debug("extract_json: trailing content after JSON: %r", text[end_pos:end_pos+50])
        return obj
    except json.JSONDecodeError as e:
        logger.debug("extract_json: Strategy1 failed: %s", e)

    # Strategy 2: Fallback - try to find JSON by brace counting (for malformed cases)
    # This handles cases where raw_decode fails but there's still parseable JSON
    # Find first { or [ and try to match it properly
    logger.debug("extract_json: trying Strategy2 (brace counting)")
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        if start == -1:
            logger.debug("extract_json: Strategy2 no '%s' found", start_char)
            continue
        logger.debug("extract_json: Strategy2 found '%s' at position %d", start_char, start)
        # Count braces to find matching end
        depth = 0
        in_string = False
        escape_next = False
        i = start
        while i < len(text):
            ch = text[i]
            if escape_next:
                escape_next = False
                i += 1
                continue
            if ch == '\\':
                escape_next = True
                i += 1
                continue
            if ch == '"':
                in_string = not in_string
                i += 1
                continue
            if in_string:
                i += 1
                continue
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    # Found matching end
                    try:
                        result = json.loads(text[start:i + 1])
                        logger.debug("extract_json: Strategy2 success, start=%d, end=%d", start, i+1)
                        return result
                    except json.JSONDecodeError as e2:
                        logger.debug("extract_json: Strategy2 json.loads failed: %s", e2)
                        break
            i += 1

    logger.debug("extract_json: all strategies failed, returning None")
    return None