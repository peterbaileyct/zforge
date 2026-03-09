"""Tests for ZForgeConfig llm_nodes round-trip, defaults, and backward compat."""

from __future__ import annotations

import json

from zforge.models.zforge_config import LlmNodeConfig, ZForgeConfig
from zforge.services.config_service import ConfigService


class TestLlmNodeConfig:
    def test_to_dict(self):
        cfg = LlmNodeConfig(provider="OpenAI", model="gpt-5-nano")
        assert cfg.to_dict() == {"provider": "OpenAI", "model": "gpt-5-nano"}

    def test_from_dict(self):
        cfg = LlmNodeConfig.from_dict({"provider": "Anthropic", "model": "claude-sonnet-4-20250514"})
        assert cfg.provider == "Anthropic"
        assert cfg.model == "claude-sonnet-4-20250514"

    def test_from_dict_defaults(self):
        cfg = LlmNodeConfig.from_dict({})
        assert cfg.provider == ""
        assert cfg.model == ""


class TestZForgeConfigLlmNodes:
    def test_round_trip(self):
        """llm_nodes survive to_dict → from_dict round-trip."""
        config = ZForgeConfig(
            llm_nodes={
                "world_generation": {
                    "editor": LlmNodeConfig(provider="OpenAI", model="gpt-5-nano"),
                    "designer": LlmNodeConfig(provider="Anthropic", model="claude-sonnet-4-20250514"),
                }
            }
        )
        data = config.to_dict()
        restored = ZForgeConfig.from_dict(data)

        assert "world_generation" in restored.llm_nodes
        assert restored.llm_nodes["world_generation"]["editor"].provider == "OpenAI"
        assert restored.llm_nodes["world_generation"]["editor"].model == "gpt-5-nano"
        assert restored.llm_nodes["world_generation"]["designer"].provider == "Anthropic"
        assert restored.llm_nodes["world_generation"]["designer"].model == "claude-sonnet-4-20250514"

    def test_json_round_trip(self):
        """Full JSON serialize/deserialize cycle."""
        config = ZForgeConfig(
            llm_nodes={
                "world_generation": {
                    "editor": LlmNodeConfig(provider="Google", model="gemini-2.0-flash"),
                }
            }
        )
        raw = json.dumps(config.to_dict())
        data = json.loads(raw)
        restored = ZForgeConfig.from_dict(data)

        assert restored.llm_nodes["world_generation"]["editor"].provider == "Google"
        assert restored.llm_nodes["world_generation"]["editor"].model == "gemini-2.0-flash"

    def test_backward_compat_no_llm_nodes(self):
        """Loading a config dict without llm_nodes still works."""
        data = {
            "bundles_root": "/some/path",
            "chat_context_size": 8192,
        }
        config = ZForgeConfig.from_dict(data)
        assert config.llm_nodes == {}
        assert config.bundles_root == "/some/path"

    def test_other_fields_preserved(self):
        """Adding llm_nodes doesn't break other fields."""
        config = ZForgeConfig(
            bundles_root="/bundles",
            chat_context_size=16384,
            llm_nodes={
                "world_generation": {
                    "editor": LlmNodeConfig(provider="OpenAI", model="gpt-5-nano"),
                }
            },
        )
        data = config.to_dict()
        assert data["bundles_root"] == "/bundles"
        assert data["chat_context_size"] == 16384
        assert "llm_nodes" in data


class TestConfigServiceDefaults:
    def test_apply_defaults_populates_llm_nodes(self):
        """_apply_defaults fills in world_generation editor/designer defaults."""
        config = ZForgeConfig()
        ConfigService._apply_defaults(config)

        assert "world_generation" in config.llm_nodes
        editor = config.llm_nodes["world_generation"]["editor"]
        designer = config.llm_nodes["world_generation"]["designer"]
        assert editor.provider == "OpenAI"
        assert editor.model == "gpt-5-nano"
        assert designer.provider == "OpenAI"
        assert designer.model == "gpt-5-nano"

    def test_apply_defaults_preserves_existing(self):
        """_apply_defaults does not overwrite user-set values."""
        config = ZForgeConfig(
            llm_nodes={
                "world_generation": {
                    "editor": LlmNodeConfig(provider="Anthropic", model="claude-sonnet-4-20250514"),
                }
            }
        )
        ConfigService._apply_defaults(config)

        # editor should be preserved
        assert config.llm_nodes["world_generation"]["editor"].provider == "Anthropic"
        # designer should be filled in
        assert config.llm_nodes["world_generation"]["designer"].provider == "OpenAI"

    def test_apply_defaults_preserves_other_processes(self):
        """_apply_defaults doesn't touch nodes for other processes."""
        config = ZForgeConfig(
            llm_nodes={
                "experience_generation": {
                    "author": LlmNodeConfig(provider="Google", model="gemini-2.0-flash"),
                }
            }
        )
        ConfigService._apply_defaults(config)

        assert config.llm_nodes["experience_generation"]["author"].provider == "Google"
        assert "world_generation" in config.llm_nodes
