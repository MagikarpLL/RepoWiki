# RepoWiki

**Open-source DeepWiki alternative** — generate comprehensive wiki documentation for any codebase from your terminal or browser.

[![PyPI](https://img.shields.io/pypi/v/repowiki.svg)](https://pypi.org/project/repowiki/)
[![Python](https://img.shields.io/pypi/pyversions/repowiki.svg)](https://pypi.org/project/repowiki/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[中文文档](README_CN.md)

## Why RepoWiki?

| | DeepWiki | deepwiki-open | **RepoWiki** |
|---|---------|--------------|-------------|
| Deploy | SaaS only | Docker Compose | **`pip install repowiki`** |
| Local repos | No | No | **Yes** |
| CLI | No | No | **Yes** |
| Web UI | Yes | Yes | **Yes** |
| Export | Web only | Web only | **Markdown / JSON / HTML** |
| Reading guide | No | No | **PageRank + guided path** |
| Terminal Q&A | No | No | **`repowiki chat`** |
| Dependencies | N/A | Docker + PostgreSQL | **Python + SQLite** |

## Quick Start

### Install via pip

```bash
pip install repowiki

# set your API key (DeepSeek, OpenAI, Anthropic, etc.)
export DEEPSEEK_API_KEY=sk-xxx
# or
repowiki config set api_key sk-xxx

# scan a local project
repowiki scan ./my-project

# scan a GitHub repo
repowiki scan https://github.com/pallets/flask

# generate self-contained HTML
repowiki scan ./my-project --format html --open

# start the web interface
pip install repowiki[web]
repowiki serve
```

### Run from source (no installation required)

If you prefer not to install via pip, you can run RepoWiki directly from the source code:

```bash
# Clone the repository
git clone https://github.com/he-yufeng/RepoWiki.git
cd RepoWiki

# Set your API key (DeepSeek, OpenAI, Anthropic, etc.)
export DEEPSEEK_API_KEY=sk-xxx

# Run directly with Python
python -m repowiki scan ./my-project

# Run with config.json in project root
# Create config.json in the project root you want to document:
# {
#   "model": "minimax",
#   "api_key": "YOUR_API_KEY",
#   "api_base": "https://api.minimax.chat/v1",
#   "language": "zh",
#   "output_dir": "./wiki",
#   "generation_mode": "full",
#   "project_path": "."
# }
python -m repowiki scan

# Generate HTML output
python -m repowiki scan --format html --open

# Start the web interface
pip install repowiki[web]
python -m repowiki serve
```

**How it works:** The `python -m repowiki` command runs the package directly from `src/repowiki/`. When you run `scan` without specifying a path, it automatically reads `config.json` from the current working directory to get the `project_path` and other settings.

## Features

### Wiki Generation
Automatically generates structured documentation for any codebase:
- **Project overview** — what it does, tech stack, setup instructions
- **Module documentation** — purpose, key files, relationships, important functions
- **Architecture diagrams** — auto-detected architecture type with Mermaid visualizations
- **Reading guide** — "start here" path based on PageRank file importance ranking
- **Bundle-aware scanner** — skips minified JS/CSS and generated frontend chunks before they burn LLM context

### Multiple Output Formats
- **Markdown** — directory of `.md` files, ready to commit to your repo
- **JSON** — structured data for API consumption or custom rendering
- **HTML** — self-contained single file, share with anyone (Mermaid diagrams included)

### Web Interface
Three-column wiki viewer with sidebar navigation, Mermaid diagram rendering, and an AI-powered Q&A chat about the codebase.

### CLI-First Design
Everything works from the terminal. No Docker, no database server, no web browser required.

```bash
repowiki scan .                    # generate wiki
repowiki scan . -f html --open     # open in browser
repowiki scan . -l zh              # Chinese output
repowiki chat .                    # ask questions (coming soon)
repowiki config list               # show configuration
```

## Supported Languages

Python, JavaScript, TypeScript, Go, Rust, Java, Kotlin, C/C++, C#, Ruby, PHP, Swift, Dart, Vue, Svelte, and 30+ more.

## Supported LLM Providers

Powered by [litellm](https://github.com/BerriAI/litellm), RepoWiki works with 100+ LLM providers:

| Provider | Model | Alias |
|----------|-------|-------|
| Anthropic | Claude Opus 4.6 | `opus` |
| Anthropic | Claude Sonnet 4.6 | `claude` |
| OpenAI | GPT-5.4 | `gpt` |
| OpenAI | GPT-5.4 Mini | `gpt-mini` |
| Google | Gemini 3.1 Pro | `gemini` |
| Google | Gemini 2.5 Flash | `gemini-flash` |
| DeepSeek | DeepSeek V3.2 | `deepseek` |
| Alibaba | Qwen3.5 Plus | `qwen` |
| Moonshot | Kimi K2.6 | `kimi` |
| Zhipu | GLM-5 | `glm` |
| MiniMax | M2.7 | `minimax` |

```bash
repowiki config set model deepseek    # use alias
repowiki scan . -m gpt                # or pass directly
```

## Configuration

RepoWiki looks for config in this order:
1. CLI flags (`-m`, `-l`, `-o`)
2. Environment variables (`REPOWIKI_MODEL`, `REPOWIKI_API_KEY`)
3. Config file (`./config.json` in current directory, or `~/.repowiki/config.json` as fallback)
4. Provider-specific env vars (`DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`)

### Config File

Create a `config.json` in your project root:

```json
{
  "model": "minimax",
  "api_key": "YOUR_API_KEY",
  "api_base": "https://api.minimax.chat/v1",
  "language": "zh",
  "output_dir": "./wiki",
  "generation_mode": "full",
  "retry_failed": true,
  "project_path": "."
}
```

| Option | Values | Description |
|--------|--------|-------------|
| `model` | Model name or alias | LLM model to use |
| `api_key` | String | API key for the LLM provider |
| `api_base` | URL | Base URL for the API (optional) |
| `language` | `en`, `zh`, `ja`, `ko` | Output language |
| `output_dir` | Path | Where to write wiki output (default: `./wiki`) |
| `generation_mode` | `full`, `incremental`, `resume` | `full`=delete all and clear cache, `incremental`=skip unchanged, `resume`=skip already successful |
| `retry_failed` | `true`, `false` | `true`=automatically retry failed docs up to 2 times, `false`=fail fast on error |
| `project_path` | Path | Project root path to scan (default: `.`) |

### Config Options Detail

#### `model`
- **Type:** String
- **Options:** Model name (e.g., `gpt-4`, `deepseek-v3`) or alias (e.g., `gpt`, `deepseek`, `minimax`)
- **Default:** `gpt`
- **Description:** The LLM model used for generating documentation. Using an alias is recommended for simplicity. See [Supported LLM Providers](#supported-llm-providers) for available models.

#### `api_key`
- **Type:** String
- **Required:** Yes
- **Description:** Your API key for the LLM provider. Can also be set via environment variable `REPOWIKI_API_KEY` or provider-specific vars like `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`.

#### `api_base`
- **Type:** String (URL)
- **Required:** No
- **Description:** Custom API base URL. Use this when you have a proxy or custom endpoint. Example: `https://api.deepseek.com/v1`

#### `language`
- **Type:** String
- **Options:** `en` (English), `zh` (Chinese), `ja` (Japanese), `ko` (Korean)
- **Default:** `en`
- **Description:** The output language for generated documentation. Affects all generated content including titles, descriptions, and technical terms.

#### `output_dir`
- **Type:** String (path)
- **Default:** `./wiki`
- **Description:** Directory where generated wiki files will be written. For Markdown format, this should be a directory path. For HTML format, this can be a file path ending in `.html`.

#### `generation_mode`
- **Type:** String
- **Options:**
  - `full` — Delete all existing files in output_dir and regenerate everything from scratch
  - `incremental` — Skip writing wiki pages whose content hasn't changed (based on hash comparison)
  - `resume` — Resume from interruption: skip successfully generated docs, retry failed/pending docs
- **Default:** `full`
- **Description:** Controls how existing output is handled and how to handle failures:
  - Use `incremental` to save time when regenerating for a project that hasn't changed much (skips writing unchanged pages, but still analyzes all docs via LLM)
  - Use `resume` to pick up from where you left off after a failure or interruption (tracks doc generation status in `.repowiki_doc_status.json`, skips successful docs and retries failed/pending ones)

#### `cache_mode`
- **Type:** String
- **Options:**
  - `reuse` — Check cache key (based on file content hash) and skip regeneration if content hasn't changed
  - `clear` — Delete all cache and regenerate from scratch
- **Default:** `reuse`
- **Description:** Controls SQLite caching behavior. `reuse` significantly speeds up re-scans by skipping files whose content hasn't changed.

#### `retry_failed`
- **Type:** Boolean
- **Options:** `true`, `false`
- **Default:** `true`
- **Description:** When `true`, failed documentation generation will be automatically retried up to 2 times with exponential backoff. When `false`, errors fail immediately.

#### `project_path`
- **Type:** String (path)
- **Default:** `.`
- **Description:** Path to the project root that will be scanned. Can be a local directory path or a GitHub URL (e.g., `https://github.com/pallets/flask`).

## Project Structure

```
RepoWiki/
├── src/repowiki/
│   ├── cli.py              # Click CLI with scan/serve/chat/config commands
│   ├── config.py           # Configuration management
│   ├── core/
│   │   ├── scanner.py      # File scanning with language detection
│   │   ├── analyzer.py     # Multi-step LLM analysis pipeline
│   │   ├── graph.py        # Dependency graph + PageRank
│   │   ├── wiki_builder.py # Wiki page assembly
│   │   ├── rag.py          # TF-IDF retrieval for Q&A
│   │   └── cache.py        # SQLite caching
│   ├── llm/
│   │   ├── client.py       # litellm async wrapper
│   │   └── prompts.py      # Structured prompt templates
│   ├── ingest/
│   │   ├── local.py        # Local directory ingestion
│   │   └── github.py       # Git clone with caching
│   ├── export/
│   │   ├── markdown.py     # Markdown directory export
│   │   ├── json_export.py  # JSON export
│   │   └── html.py         # Self-contained HTML export
│   └── server/             # FastAPI web backend
├── frontend/               # React + Vite + TailwindCSS
├── pyproject.toml
└── LICENSE
```

## How It Works

1. **Scan** — Walk the directory tree, filter out binaries, generated bundles, and oversized files, detect languages and entry points
2. **Graph** — Parse import statements across 6 languages, build a dependency graph, run PageRank to rank file importance
3. **Analyze** — Send file tree + key files to LLM in 4 structured passes (overview, modules, architecture, reading guide)
4. **Cache** — Store results in SQLite keyed by content hash, skip unchanged files on re-scan
5. **Export** — Assemble wiki pages with Mermaid diagrams and source links, output in chosen format

## Development

```bash
git clone https://github.com/he-yufeng/RepoWiki.git
cd RepoWiki

# backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,web]"

# frontend
cd frontend && npm install && npm run dev

# run backend
repowiki serve --port 8000
```

## Related Projects

- [**CodeJoust**](https://github.com/he-yufeng/CodeJoust) — once RepoWiki tells you *how* the repo works, CodeJoust helps you change it: race Claude Code, aider, Codex, and Gemini on the same bug in parallel git worktrees, auto-score by tests/cost/diff/time, merge the winner. `pip install codejoust`.
- [**LiteBench**](https://github.com/he-yufeng/LiteBench) — one-command LLM/agent benchmark. HumanEval/GSM8K/MMLU/MATH-500 built in, plus YAML-defined custom tasks and a single-file HTML dashboard.
- [**CoreCoder**](https://github.com/he-yufeng/CoreCoder) — Claude Code's architecture distilled to ~1,400 lines of Python, with 7 deep-dive architecture articles.
- [**AnyCoder**](https://github.com/he-yufeng/AnyCoder) — practical terminal AI coding agent, 100+ model support via litellm.

## License

MIT
