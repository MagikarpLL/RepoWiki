# RepoWiki

**开源 DeepWiki 替代品** — 从终端或浏览器为任意代码仓库生成完整 wiki 文档。

[![PyPI](https://img.shields.io/pypi/v/repowiki.svg)](https://pypi.org/project/repowiki/)
[![Python](https://img.shields.io/pypi/pyversions/repowiki.svg)](https://pypi.org/project/repowiki/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[English](README.md)

## 为什么选 RepoWiki？

| | DeepWiki | deepwiki-open | **RepoWiki** |
|---|---------|--------------|-------------|
| 部署方式 | SaaS，不可自托管 | Docker Compose | **`pip install repowiki`** |
| 本地仓库 | 不支持 | 不支持 | **原生支持** |
| CLI | 无 | 无 | **有** |
| Web UI | 有 | 有 | **有** |
| 导出格式 | 仅网页 | 仅网页 | **Markdown / JSON / HTML** |
| 阅读指南 | 无 | 无 | **PageRank 排名 + 阅读路径** |
| 终端问答 | 无 | 无 | **`repowiki chat`** |
| 依赖 | N/A | Docker + PostgreSQL | **Python + SQLite** |

## 快速开始

### pip 安装

```bash
pip install repowiki

# 设置 API Key（DeepSeek、OpenAI、Anthropic 等）
export DEEPSEEK_API_KEY=sk-xxx
# 或者
repowiki config set api_key sk-xxx

# 扫描本地项目
repowiki scan ./my-project

# 扫描 GitHub 仓库
repowiki scan https://github.com/pallets/flask

# 生成自包含 HTML 并打开
repowiki scan ./my-project --format html --open

# 启动 Web 界面
pip install repowiki[web]
repowiki serve
```

### 源码运行（无需安装）

如果不希望通过 pip 安装，可以直接运行源码：

```bash
# 克隆仓库
git clone https://github.com/he-yufeng/RepoWiki.git
cd RepoWiki

# 设置 API Key（DeepSeek、OpenAI、Anthropic 等）
export DEEPSEEK_API_KEY=sk-xxx

# 直接运行（指定项目路径）
python -m repowiki scan ./my-project

# 使用 config.json（放在项目根目录）
# 在要文档化的项目根目录创建 config.json：
# {
#   "model": "minimax",
#   "api_key": "YOUR_API_KEY",
#   "api_base": "https://api.minimax.chat/v1",
#   "language": "zh",
#   "output_dir": "./wiki",
#   "generation_mode": "full",
#   "cache_mode": "reuse",
#   "retry_failed": true,
#   "project_path": "."
# }
python -m repowiki scan

# 生成 HTML 并打开
python -m repowiki scan --format html --open

# 启动 Web 界面
pip install repowiki[web]
python -m repowiki serve
```

**原理：** `python -m repowiki` 直接从 `src/repowiki/` 运行。当不指定路径时，它会自动读取当前工作目录下的 `config.json`，获取 `project_path` 等配置。

## 核心功能

### Wiki 生成
自动为任意代码仓库生成结构化文档：
- **项目概览** — 做什么、技术栈、如何运行
- **模块文档** — 用途、关键文件、模块间关系、重要函数
- **架构图** — 自动识别架构模式，Mermaid 可视化
- **阅读指南** — 基于 PageRank 文件重要性排名的"从这里开始读"路径
- **Bundle 感知扫描** — 先跳过 minified JS/CSS 和生成式前端 chunk，避免浪费 LLM 上下文

### 多格式导出
- **Markdown** — `.md` 文件目录，可以直接放进仓库当文档用
- **JSON** — 结构化数据，方便 API 消费或自定义渲染
- **HTML** — 自包含单文件，分享给任何人都能直接打开（内含 Mermaid 图表）

### Web 界面
三栏布局 wiki 查看器：侧边导航 + 内容区 + Mermaid 图表，还有 AI 问答聊天功能。

### CLI 优先
所有功能都能在终端完成。不需要 Docker，不需要数据库，不需要浏览器。

```bash
repowiki scan .                    # 生成 wiki
repowiki scan . -f html --open     # 浏览器打开
repowiki scan . -l zh              # 中文输出
repowiki chat .                    # 终端问答（即将推出）
repowiki config list               # 查看配置
```

## 支持的语言

Python、JavaScript、TypeScript、Go、Rust、Java、Kotlin、C/C++、C#、Ruby、PHP、Swift、Dart、Vue、Svelte 等 30+ 种编程语言。

## 支持的 LLM 提供商

基于 [litellm](https://github.com/BerriAI/litellm)，支持 100+ LLM 提供商：

| 提供商 | 模型 | 别名 |
|--------|------|------|
| Anthropic | Claude Opus 4.6 | `opus` |
| Anthropic | Claude Sonnet 4.6 | `claude` |
| OpenAI | GPT-5.4 | `gpt` |
| OpenAI | GPT-5.4 Mini | `gpt-mini` |
| Google | Gemini 3.1 Pro | `gemini` |
| Google | Gemini 2.5 Flash | `gemini-flash` |
| DeepSeek | DeepSeek V3.2 | `deepseek` |
| 阿里云 | Qwen3.5 Plus | `qwen` |
| 月之暗面 | Kimi K2.6 | `kimi` |
| 智谱 | GLM-5 | `glm` |
| MiniMax | M2.7 | `minimax` |

## 配置

RepoWiki 按以下优先级获取配置：
1. CLI 参数 (`-m`, `-l`, `-o`)
2. 环境变量 (`REPOWIKI_MODEL`, `REPOWIKI_API_KEY`)
3. 配置文件（当前目录的 `./config.json`，或 `~/.repowiki/config.json` 作为备选）
4. 提供商特定的环境变量 (`DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`)

### 配置文件

在项目根目录创建 `config.json`：

```json
{
  "model": "minimax",
  "api_key": "YOUR_API_KEY",
  "api_base": "https://api.minimax.chat/v1",
  "language": "zh",
  "output_dir": "./wiki",
  "generation_mode": "full",
  "cache_mode": "reuse",
  "retry_failed": true,
  "project_path": "."
}
```

| 参数 | 可选值 | 说明 |
|------|--------|------|
| `model` | 模型名或别名 | 使用的 LLM 模型 |
| `api_key` | 字符串 | LLM 提供商的 API 密钥 |
| `api_base` | URL | API 基础地址（可选） |
| `language` | `en`, `zh`, `ja`, `ko` | 输出语言 |
| `output_dir` | 路径 | wiki 输出目录（默认：`./wiki`） |
| `generation_mode` | `full`, `incremental`, `resume` | `full`=删除全部，`incremental`=跳过未变更，`resume`=重试失败/未完成文档 |
| `cache_mode` | `reuse`, `clear` | `reuse`=检查缓存跳过未变更文件，`clear`=清除缓存重新生成 |
| `retry_failed` | `true`, `false` | `true`=自动重试失败的文档最多 2 次，`false`=快速失败 |
| `project_path` | 路径 | 要扫描的项目根目录（默认：`.`） |

### 配置参数详解

#### `model`
- **类型:** 字符串
- **可选值:** 模型名（如 `gpt-4`、`deepseek-v3`）或别名（如 `gpt`、`deepseek`、`minimax`）
- **默认值:** `gpt`
- **说明:** 用于生成文档的 LLM 模型。建议使用别名简化配置。详见[支持的 LLM 提供商](#支持的-llm-提供商)。

#### `api_key`
- **类型:** 字符串
- **必填:** 是
- **说明:** LLM 提供商的 API 密钥。也可通过环境变量 `REPOWIKI_API_KEY` 或提供商特定变量（如 `DEEPSEEK_API_KEY`、`OPENAI_API_KEY`）设置。

#### `api_base`
- **类型:** 字符串（URL）
- **必填:** 否
- **说明:** 自定义 API 地址。当你使用代理或自定义端点时使用。示例：`https://api.deepseek.com/v1`

#### `language`
- **类型:** 字符串
- **可选值:** `en`（英语）、`zh`（中文）、`ja`（日语）、`ko`（韩语）
- **默认值:** `en`
- **说明:** 生成文档的输出语言。会影响所有生成的内容，包括标题、描述和技术术语。

#### `output_dir`
- **类型:** 字符串（路径）
- **默认值:** `./wiki`
- **说明:** 生成 wiki 文件的写入目录。对于 Markdown 格式，这应该是目录路径。对于 HTML 格式，这可以是`.html`结尾的文件路径。

#### `generation_mode`
- **类型:** 字符串
- **可选值:**
  - `full` — 删除 output_dir 中的所有现有文件，从头重新生成
  - `incremental` — 跳过内容未发生变化的 wiki 页面的写入（基于 hash 比较）
  - `resume` — 从中断处继续：跳过已成功生成的文档，重试失败/未完成的文档
- **默认值:** `full`
- **说明:** 控制如何处理现有输出以及如何处理失败：
  - 使用 `incremental` 可以节省时间，当重新生成没有太多变化的项目时（跳过写入未变更的页面，但仍然通过 LLM 分析所有文档）
  - 使用 `resume` 可以从上次中断的地方继续（状态记录在 `.repowiki_doc_status.json` 中，跳过成功的文档并重试失败/未完成的文档）

#### `cache_mode`
- **类型:** 字符串
- **可选值:**
  - `reuse` — 检查缓存键（基于文件内容 hash），如果内容未变则跳过生成
  - `clear` — 删除所有缓存并从头重新生成
- **默认值:** `reuse`
- **说明:** 控制 SQLite 缓存行为。`reuse` 通过跳过内容未变的文件来显著加快重新扫描速度。

#### `retry_failed`
- **类型:** 布尔值
- **可选值:** `true`, `false`
- **默认值:** `true`
- **说明:** 当为 `true` 时，失败的文档生成会自动重试最多 2 次（指数退避）。当为 `false` 时，错误会立即失败。

#### `project_path`
- **类型:** 字符串（路径）
- **默认值:** `.`
- **说明:** 要扫描的项目根目录路径。可以是本地目录路径或 GitHub URL（如 `https://github.com/pallets/flask`）。

## 工作原理

1. **扫描** — 遍历目录树，过滤二进制、生成式 bundle 和超大文件，检测语言和入口文件
2. **建图** — 解析 6 种语言的 import 语句，构建依赖图，PageRank 计算文件重要性
3. **分析** — 4 步 LLM 分析（概览、模块、架构、阅读指南），并发执行
4. **缓存** — SQLite 按内容 hash 缓存，重新扫描时跳过未变更文件
5. **导出** — 组装 wiki 页面，注入 Mermaid 图和源码链接，按选定格式输出

## 开发

```bash
git clone https://github.com/he-yufeng/RepoWiki.git
cd RepoWiki

# 后端
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,web]"

# 前端
cd frontend && npm install && npm run dev

# 启动后端
repowiki serve --port 8000
```

## 许可证

MIT
