"""Tests for per-node LLM connector resolution in world creation graph.

Verifies that build_create_world_graph() correctly wires different
connectors to the editor and designer nodes, and that
ZForgeManager._resolve_node_connector() handles overrides and fallbacks.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from zforge.models.zforge_config import LlmNodeConfig, ZForgeConfig
from zforge.services.llm.connector_registry import ConnectorRegistry
from zforge.services.llm.llm_connector import LlmConnector


def _make_mock_connector(name: str) -> LlmConnector:
    """Create a mock LlmConnector with a distinct identity."""
    connector = MagicMock(spec=LlmConnector)
    connector.get_name.return_value = name
    connector.get_context_size.return_value = 8192
    connector.get_model.return_value = MagicMock()
    return connector


class TestBuildCreateWorldGraphPerNode:
    """Verify that each node gets its own connector."""

    def test_editor_and_designer_get_different_connectors(self):
        """build_create_world_graph passes the correct connector to each node."""
        editor_conn = _make_mock_connector("EditorProvider")
        designer_conn = _make_mock_connector("DesignerProvider")

        # Patch the finalizer's zworld_manager dependency to avoid import-time errors
        with patch(
            "zforge.graphs.world_creation_graph._make_finalizer_node",
            return_value=lambda state: {},
        ):
            from zforge.graphs.world_creation_graph import build_create_world_graph

            _graph = build_create_world_graph(
                editor_connector=editor_conn,
                designer_connector=designer_conn,
                editor_model="model-a",
                designer_model="model-b",
            )

        editor_conn.get_model.assert_called_once_with("model-a")
        designer_conn.get_model.assert_called_once_with("model-b")

    def test_none_model_uses_connector_default(self):
        """When model is None, get_model(None) is called (connector decides)."""
        conn = _make_mock_connector("Provider")

        with patch(
            "zforge.graphs.world_creation_graph._make_finalizer_node",
            return_value=lambda state: {},
        ):
            from zforge.graphs.world_creation_graph import build_create_world_graph

            _graph = build_create_world_graph(
                editor_connector=conn,
                designer_connector=conn,
            )

        # get_model called twice (once per node), each with None
        assert conn.get_model.call_count == 2
        for call in conn.get_model.call_args_list:
            assert call == ((None,),) or call == ((), {"model_name": None}) or call.args == (None,)


class TestResolveNodeConnector:
    """Test ZForgeManager._resolve_node_connector logic."""

    def _make_manager(self, config: ZForgeConfig, registry: ConnectorRegistry):
        """Minimal ZForgeManager with mocked dependencies."""
        from zforge.managers.zforge_manager import ZForgeManager

        mgr = object.__new__(ZForgeManager)
        mgr._connector_registry = registry
        mgr._config = config
        mgr._llm_connector = registry.get_default()
        mgr._world_creation_graph = None
        return mgr

    def test_resolves_configured_provider(self):
        registry = ConnectorRegistry()
        openai = _make_mock_connector("OpenAI")
        anthropic = _make_mock_connector("Anthropic")
        registry.register(openai)
        registry.register(anthropic)

        config = ZForgeConfig(
            llm_nodes={
                "world_generation": {
                    "editor": LlmNodeConfig(provider="Anthropic", model="claude-sonnet-4-20250514"),
                }
            }
        )
        mgr = self._make_manager(config, registry)

        connector, model = mgr._resolve_node_connector("world_generation", "editor")
        assert connector is anthropic
        assert model == "claude-sonnet-4-20250514"

    def test_falls_back_to_default_when_provider_missing(self):
        registry = ConnectorRegistry()
        default_conn = _make_mock_connector("OpenAI")
        registry.register(default_conn)

        config = ZForgeConfig()  # no llm_nodes at all
        mgr = self._make_manager(config, registry)

        connector, model = mgr._resolve_node_connector("world_generation", "editor")
        assert connector is default_conn
        assert model is None

    def test_falls_back_when_provider_not_in_registry(self):
        registry = ConnectorRegistry()
        default_conn = _make_mock_connector("OpenAI")
        registry.register(default_conn)

        config = ZForgeConfig(
            llm_nodes={
                "world_generation": {
                    "editor": LlmNodeConfig(provider="UnknownProvider", model="some-model"),
                }
            }
        )
        mgr = self._make_manager(config, registry)

        connector, model = mgr._resolve_node_connector("world_generation", "editor")
        assert connector is default_conn
        assert model is None

    def test_different_nodes_resolve_independently(self):
        registry = ConnectorRegistry()
        openai = _make_mock_connector("OpenAI")
        google = _make_mock_connector("Google")
        registry.register(openai)
        registry.register(google)

        config = ZForgeConfig(
            llm_nodes={
                "world_generation": {
                    "editor": LlmNodeConfig(provider="OpenAI", model="gpt-5-nano"),
                    "designer": LlmNodeConfig(provider="Google", model="gemini-2.0-flash"),
                }
            }
        )
        mgr = self._make_manager(config, registry)

        editor_conn, editor_model = mgr._resolve_node_connector("world_generation", "editor")
        designer_conn, designer_model = mgr._resolve_node_connector("world_generation", "designer")

        assert editor_conn is openai
        assert editor_model == "gpt-5-nano"
        assert designer_conn is google
        assert designer_model == "gemini-2.0-flash"

    def test_empty_provider_falls_back_to_default(self):
        registry = ConnectorRegistry()
        default_conn = _make_mock_connector("OpenAI")
        registry.register(default_conn)

        config = ZForgeConfig(
            llm_nodes={
                "world_generation": {
                    "editor": LlmNodeConfig(provider="", model=""),
                }
            }
        )
        mgr = self._make_manager(config, registry)

        connector, model = mgr._resolve_node_connector("world_generation", "editor")
        assert connector is default_conn
        assert model is None
