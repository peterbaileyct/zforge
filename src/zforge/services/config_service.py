"""Configuration persistence service.

Loads/saves ZForgeConfig as JSON via platformdirs.
Implements: src/zforge/services/config_service.py per docs/ER Diagram.md.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from platformdirs import user_config_dir

from zforge.models.process_config import PROCESSES
from zforge.models.zforge_config import LlmNodeConfig, ZForgeConfig


_CONFIG_DIR = user_config_dir("zforge")
_CONFIG_FILE = "zforge_config.json"


class ConfigService:
    """Persists ZForgeConfig as a JSON file in the user config directory."""

    def __init__(self) -> None:
        self._config_path = Path(_CONFIG_DIR) / _CONFIG_FILE

    def load(self) -> ZForgeConfig:
        """Load config from disk, or return defaults if unavailable."""
        if self._config_path.exists():
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            config = ZForgeConfig.from_dict(data)
        else:
            config = ZForgeConfig()
        self._apply_defaults(config)
        return config

    def exists(self) -> bool:
        """Return True if a configuration file already exists on disk."""
        return self._config_path.exists()

    def has_llm_config(self) -> bool:
        """Return True if the on-disk config has a non-empty llm_nodes section."""
        if not self._config_path.exists():
            return False
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            nodes = data.get("llm_nodes", {})
            return bool(nodes)
        except Exception:
            return False

    def save(self, config: ZForgeConfig) -> None:
        """Save config to disk."""
        os.makedirs(self._config_path.parent, exist_ok=True)
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f, indent=2)

    @staticmethod
    def _apply_defaults(config: ZForgeConfig) -> None:
        """Fill in default paths if not set (desktop only)."""
        home = Path.home()
        if not config.bundles_root:
            config.bundles_root = str(home / "zforge" / "bundles")
        if not config.experience_folder:
            config.experience_folder = str(home / "zforge" / "experiences")
        # Guard against stale on-disk configs with the original 512-token default.
        # 512 tokens is insufficient for any useful LLM interaction.
        _MIN_CONTEXT_SIZE = 4096
        if config.chat_context_size < _MIN_CONTEXT_SIZE:
            config.chat_context_size = 8192

        # Ensure per-node LLM defaults exist for every known process/node.
        for proc in PROCESSES:
            proc_nodes = config.llm_nodes.setdefault(proc.slug, {})
            for node in proc.nodes:
                if node.slug not in proc_nodes:
                    proc_nodes[node.slug] = LlmNodeConfig(
                        provider=node.default_provider,
                        model=node.default_model,
                    )
