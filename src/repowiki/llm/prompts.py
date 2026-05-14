"""prompt templates for repowiki analysis pipeline."""

from __future__ import annotations

import json
import re


def _lang_instruction(language: str) -> str:
    lang_map = {
        "en": "Respond in English.",
        "zh": "请用中文回答。",
        "ja": "日本語で回答してください。",
        "ko": "한국어로 답변해주세요.",
    }
    return lang_map.get(language, "Respond in English.")


def _json_instruction() -> str:
    return (
        "Output ONLY valid JSON. No markdown fences, no explanation text before or after. "
        "Just the JSON object/array."
    )


def build_overview_prompt(file_tree: str, key_files: str, language: str = "en") -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "You are a senior software engineer explaining a project to a new team member. "
                "Be direct, specific, and concrete. "
                "Do NOT use filler phrases like 'leveraging', 'utilizing', 'cutting-edge', "
                "'robust', or 'comprehensive'. Just describe what things do. "
                "IMPORTANT: Think about the project structure BEFORE generating output. "
                "Identify what type of project this is and what the entry points are. "
                f"{_lang_instruction(language)}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Here is the file tree and key files of a project:\n\n"
                f"## File Tree\n```\n{file_tree}\n```\n\n"
                f"## Key Files\n{key_files}\n\n"
                "Generate a project overview as JSON with this structure:\n"
                "{\n"
                '  "name": "project name",\n'
                '  "one_liner": "what this project does in one sentence (max 20 words)",\n'
                '  "description": "2-3 paragraphs explaining the project in plain language",\n'
                '  "project_type": "one of: backend-app, frontend-app, cli-tool, library, full-stack, monorepo, or unknown",\n'
                '  "entry_points": ["main.py", "app.py"] // files that likely start the application\n'
                '  "tech_stack": [{"name": "Python", "category": "language", "version": "3.10+"}],\n'
                '  "setup_instructions": ["step 1", "step 2"],\n'
                '  "key_features": ["feature 1", "feature 2"]\n'
                "}\n\n"
                "CRITICAL: Analyze the file structure to determine project_type:\n"
                "- Has package.json + src/ with components/ → frontend-app\n"
                "- Has requirements.txt/pyproject.toml + app.py/routes/ → backend-app\n"
                "- Has package.json with bin/ entry → cli-tool\n"
                "- Has no UI files, mostly library code → library\n"
                "- Has both frontend markers AND backend markers → full-stack\n"
                "- Has multiple packages/workspaces → monorepo\n\n"
                f"{_json_instruction()}"
            ),
        },
    ]


def build_module_prompt(
    module_name: str,
    files_context: str,
    project_summary: str,
    language: str = "en",
) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "You are a senior engineer documenting your own code. "
                "Be direct and specific. No filler. "
                "Explain what each file does, how files relate to each other, "
                "and what the key functions/classes are. "
                "IMPORTANT: For each key_symbol, you MUST include the actual source code line number "
                "where it is defined. Be precise - the line number must match the code shown. "
                f"{_lang_instruction(language)}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Project: {project_summary}\n\n"
                f"Document the '{module_name}' module. Here are its files:\n\n"
                f"{files_context}\n\n"
                "Output JSON with EXACT structure:\n"
                "{\n"
                f'  "name": "{module_name}",\n'
                '  "purpose": "one sentence describing what this module does",\n'
                '  "description": "2-3 sentences explaining the module purpose and how files work together",\n'
                '  "files": [\n'
                '    {\n'
                '      "path": "relative/path/to/file.py",\n'
                '      "purpose": "what this specific file does",\n'
                '      "key_symbols": [\n'
                '        {"name": "ClassName or function_name", "kind": "class|function|variable|constant", "line": 42, "description": "1-2 sentences: what it does and why it matters"}\n'
                '      ]\n'
                '    }\n'
                '  ],\n'
                '  "relationships": [{"source": "file_a.py", "target": "file_b.py", "description": "how they interact"}],\n'
                '  "key_concepts": [{"name": "concept name", "explanation": "why this matters"}]\n'
                "}\n\n"
                "CRITICAL REQUIREMENTS:\n"
                "- For each key_symbol, you MUST specify the 'line' number where it appears in the source\n"
                "- The 'kind' must be one of: class, function, method, variable, constant, decorator\n"
                "- 'description' should explain what the symbol does and its importance to the module\n"
                "- List only the MOST important symbols per file (max 5 per file)\n"
                "- Do NOT invent line numbers - only include symbols where you can see the actual line\n\n"
                f"{_json_instruction()}"
            ),
        },
    ]


def build_architecture_prompt(
    file_tree: str,
    key_files: str,
    language: str = "en",
) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "You are a software architect analyzing a codebase. "
                "Identify the architecture pattern and generate Mermaid diagrams. "
                "Mermaid syntax must be valid. Use simple node names (no special chars). "
                "IMPORTANT: Analyze the actual code structure to identify components, "
                "their responsibilities, and how data flows between them. "
                f"{_lang_instruction(language)}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"## File Tree\n```\n{file_tree}\n```\n\n"
                f"## Key Files\n{key_files}\n\n"
                "Analyze the architecture thoroughly. Output JSON:\n"
                "{\n"
                '  "architecture_type": "one of: monolith, layered, mvc, client-server, microservices, event-driven, plugin-system, pipeline, or library",\n'
                '  "description": "2-3 sentences explaining WHY this architecture was chosen and how components interact",\n'
                '  "components": [\n'
                '    {"name": "ComponentName", "purpose": "what this component does and why it exists", "files": ["file1.py", "file2.py"]}\n'
                '  ],\n'
                '  "mermaid_component": "graph TD\\n  A[Component] --> B[Component]\\n  ...",\n'
                '  "mermaid_sequence": "sequenceDiagram\\n  participant A\\n  A->>B: request\\n  ...",\n'
                '  "data_flow": "2-3 sentences describing how data moves through the system"\n'
                "}\n\n"
                "CRITICAL REQUIREMENTS:\n"
                "- architecture_type: Choose the BEST match, not just 'monolith'\n"
                "- For 'layered': identify presentation/business/data layers\n"
                "- For 'mvc': identify models, views, controllers\n"
                "- For 'client-server': identify client app vs API server\n"
                "- For 'pipeline': identify data sources, transformations, outputs\n"
                "- Each component needs a 'purpose' that explains WHY it exists\n"
                "- The mermaid_component diagram should show the MAIN components and their relationships\n"
                "- mermaid_sequence should show a typical request/response flow\n"
                "- data_flow should describe how data moves from input to output\n"
                "- Do NOT create diagrams with more than 8 nodes - focus on key components\n\n"
                "IMPORTANT: Mermaid code must be a single string with \\n for newlines. "
                "Use simple alphanumeric node IDs (no spaces, no special chars). "
                f"{_json_instruction()}"
            ),
        },
    ]


def build_reading_guide_prompt(
    rankings: str,
    module_summaries: str,
    language: str = "en",
) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "You are a mentor helping a developer understand a new codebase. "
                "Create a reading guide: which files to read, in what order, and WHY each matters. "
                "Start from entry points and configuration, then core logic, then utilities. "
                "Each step should explain WHAT to look for AND WHY this file is important to understand the codebase. "
                f"{_lang_instruction(language)}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"## File Importance Rankings (by PageRank)\n{rankings}\n\n"
                f"## Module Summaries\n{module_summaries}\n\n"
                "Create a reading guide with 5-10 steps. Output JSON:\n"
                "{\n"
                '  "introduction": "2-3 sentences on how to approach reading this codebase and what makes it unique",\n'
                '  "steps": [\n'
                '    {"order": 1, "title": "step title", "files": ["file1.py", "file2.py"], '
                '"explanation": "WHY these files matter - what to look for and how it connects to the bigger picture", "time_estimate": "5 min"},\n'
                '    {"order": 2, "title": "...", "files": ["..."], '
                '"explanation": "WHY this step builds on the previous one and what new concepts it introduces", "time_estimate": "10 min"}\n'
                '  ],\n'
                '  "tips": ["general tip 1 for reading this codebase", "general tip 2"]\n'
                "}\n\n"
                "CRITICAL REQUIREMENTS:\n"
                "- Each step's 'explanation' MUST answer: WHY should I read these files? What will I understand after?\n"
                "- Do NOT just list files - explain the connection between files and what patterns to look for\n"
                "- Group files logically: entry points together, core logic together, utilities together\n"
                "- First steps should build mental model, later steps add detail\n"
                "- time_estimate should be realistic for someone new to the codebase\n"
                "- tips should cover gotchas, common pitfalls, or key things to notice\n\n"
                f"{_json_instruction()}"
            ),
        },
    ]


def build_chat_prompt(
    question: str,
    context_chunks: str,
    language: str = "en",
) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "You are a knowledgeable developer answering questions about a codebase. "
                "Answer based on the actual code shown below, not general knowledge. "
                "Reference specific files and line numbers when relevant. "
                "Be direct -- answer the question, don't give a lecture. "
                f"{_lang_instruction(language)}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"## Relevant Code\n{context_chunks}\n\n"
                f"## Question\n{question}"
            ),
        },
    ]


def extract_json(text: str) -> dict | list | None:
    """extract JSON from LLM output, handling markdown fences and extra text."""
    # strip markdown code fences
    text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$", "", text.strip(), flags=re.MULTILINE)

    # try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # find the first { or [ and match to the last } or ]
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        if start == -1:
            continue
        end = text.rfind(end_char)
        if end == -1 or end <= start:
            continue
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            continue

    return None
