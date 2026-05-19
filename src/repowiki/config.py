"""configuration management for repowiki."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path.home() / ".repowiki"
_CONFIG_FILE = _CONFIG_DIR / "config.json"

# Default limits (magic numbers extracted as constants)
DEFAULT_MAX_FILE_SIZE = 200 * 1024  # 200 KB
DEFAULT_MAX_FILES = 1000
DEFAULT_CONCURRENCY = 5
DEFAULT_OUTPUT_DIR = "./wiki"
DEFAULT_GENERATION_MODE = "full"  # full=delete all and regenerate, incremental=skip unchanged, resume=skip already successful
DEFAULT_RETRY_FAILED = True  # retry failed docs automatically
DEFAULT_PROJECT_PATH = "."  # project root path to scan
DEFAULT_LOG_DIR = ""  # empty means no log file, logs only to console

# shortcuts so users don't have to type full provider/model strings
MODEL_ALIASES = {
    "deepseek": "deepseek/deepseek-chat",
    "opus": "anthropic/claude-opus-4-6",
    "claude": "anthropic/claude-sonnet-4-6",
    "gpt": "gpt-5.4",
    "gpt-mini": "gpt-5.4-mini",
    "gemini": "gemini/gemini-3.1-pro-preview",
    "gemini-flash": "gemini/gemini-2.5-flash",
    "qwen": "openai/qwen3.5-plus",
    "kimi": "openai/kimi-k2.6",
    "glm": "openai/glm-5",
    "minimax": "openai/MiniMax-M2.7",
}


def resolve_model(name: str) -> str:
    return MODEL_ALIASES.get(name, name)


@dataclass
class Config:
    model: str = "minimax/MiniMax-M2.7"
    api_key: str = ""
    api_base: str = ""
    language: str = "en"
    max_file_size: int = DEFAULT_MAX_FILE_SIZE
    max_files: int = DEFAULT_MAX_FILES
    output_dir: str = DEFAULT_OUTPUT_DIR
    concurrency: int = DEFAULT_CONCURRENCY
    generation_mode: str = DEFAULT_GENERATION_MODE
    retry_failed: bool = DEFAULT_RETRY_FAILED
    project_path: str = DEFAULT_PROJECT_PATH
    log_dir: str = DEFAULT_LOG_DIR

    @classmethod
    def load(cls) -> Config:
        """Load config from file, then override with env vars."""
        data: dict = {}

        # Try to find config.json - first in current directory, then in ~/.repowiki/
        local_config = Path.cwd() / "config.json"
        if local_config.exists():
            try:
                data = json.loads(local_config.read_text())
                logger.debug("Loaded config from %s", local_config)
            except (json.JSONDecodeError, OSError) as e:
                logger.debug("Failed to parse local config file, using defaults: %s", e)
        elif _CONFIG_FILE.exists():
            try:
                data = json.loads(_CONFIG_FILE.read_text())
                logger.debug("Loaded config from %s", _CONFIG_FILE)
            except (json.JSONDecodeError, OSError) as e:
                logger.debug("Failed to parse config file, using defaults: %s", e)

        cfg = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

        # env overrides
        if val := os.getenv("REPOWIKI_MODEL"):
            cfg.model = val
        if val := os.getenv("REPOWIKI_API_KEY"):
            cfg.api_key = val
        if val := os.getenv("REPOWIKI_API_BASE"):
            cfg.api_base = val
        if val := os.getenv("REPOWIKI_LANG"):
            cfg.language = val
        if val := os.getenv("REPOWIKI_LOG_DIR"):
            cfg.log_dir = val

        # fall back to common provider keys
        if not cfg.api_key:
            for env_key in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "MINIMAX_API_KEY"):
                if val := os.getenv(env_key):
                    cfg.api_key = val
                    break

        cfg.model = resolve_model(cfg.model)
        return cfg

    def save(self) -> None:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "model": self.model,
            "api_key": self.api_key,
            "api_base": self.api_base,
            "language": self.language,
            "generation_mode": self.generation_mode,
            "retry_failed": self.retry_failed,
            "project_path": self.project_path,
            "log_dir": self.log_dir,
        }
        # don't persist empty values
        data = {k: v for k, v in data.items() if v}
        _CONFIG_FILE.write_text(json.dumps(data, indent=2) + "\n")

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}
