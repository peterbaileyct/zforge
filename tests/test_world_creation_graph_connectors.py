"""Tests for per-node LLM connector resolution in world creation graph.

Verifies that build_create_world_graph() correctly wires connectors
for the summarizer, entity_summarizer, and graph_extractor nodes, and that
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


def _make_mock_embedding():
    """Create a mock EmbeddingConnector."""
    emb = MagicMock()
    emb.get_embeddings.return_value = MagicMock()
    emb.model_identity.return_value = {
        "embedding_model_name": "test-model",
        "embedding_model_size_bytes": 1000,
    }
    return emb


class TestBuildCreateWorldGraphPerNode:
    """Verify that the graph builds without error and wires connectors."""

    def test_graph_builds_with_all_connectors(self):
        """build_create_world_graph accepts the new connector signature."""
        sum_conn = _make_mock_connector("SummarizerProvider")
        esum_conn = _make_mock_connector("EntitySummarizerProvider")
        gext_conn = _make_mock_connector("GraphExtractorProvider")
        emb = _make_mock_embedding()
        mgr = MagicMock()
        config = ZForgeConfig()

        from zforge.graphs.world_creation_graph import build_create_world_graph

        graph = build_create_world_graph(
            summarizer_connector=sum_conn,
            graph_extractor_connector=gext_conn,
            entity_summarizer_connector=esum_conn,
            embedding_connector=emb,
            zworld_manager=mgr,
            config=config,
            bundles_root="/tmp/test-bundles",
            summarizer_model="model-a",
            graph_extractor_model="model-c",
            entity_summarizer_model="model-d",
        )
        assert graph is not None


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
                    "summarizer": LlmNodeConfig(provider="Anthropic", model="claude-sonnet-4-20250514"),
                }
            }
        )
        mgr = self._make_manager(config, registry)

        connector, model = mgr._resolve_node_connector("world_generation", "summarizer")
        assert connector is anthropic
        assert model == "claude-sonnet-4-20250514"

    def test_falls_back_to_default_when_provider_missing(self):
        registry = ConnectorRegistry()
        default_conn = _make_mock_connector("OpenAI")
        registry.register(default_conn)

        config = ZForgeConfig()  # no llm_nodes at all
        mgr = self._make_manager(config, registry)

        connector, model = mgr._resolve_node_connector("world_generation", "summarizer")
        assert connector is default_conn
        assert model is None

    def test_falls_back_when_provider_not_in_registry(self):
        registry = ConnectorRegistry()
        default_conn = _make_mock_connector("OpenAI")
        registry.register(default_conn)

        config = ZForgeConfig(
            llm_nodes={
                "world_generation": {
                    "summarizer": LlmNodeConfig(provider="UnknownProvider", model="some-model"),
                }
            }
        )
        mgr = self._make_manager(config, registry)

        connector, model = mgr._resolve_node_connector("world_generation", "summarizer")
        assert connector is default_conn
        assert model is None

    def test_different_processes_resolve_independently(self):
        registry = ConnectorRegistry()
        openai = _make_mock_connector("OpenAI")
        google = _make_mock_connector("Google")
        registry.register(openai)
        registry.register(google)

        config = ZForgeConfig(
            llm_nodes={
                "world_generation": {
                    "summarizer": LlmNodeConfig(provider="OpenAI", model="gpt-5-nano"),
                },
                "document_parsing": {
                    "entity_summarizer": LlmNodeConfig(provider="Google", model="gemini-2.5-flash-lite"),
                    "graph_extractor": LlmNodeConfig(provider="Google", model="gemini-2.5-flash-lite"),
                },
            }
        )
        mgr = self._make_manager(config, registry)

        sum_conn, sum_model = mgr._resolve_node_connector("world_generation", "summarizer")
        esum_conn, esum_model = mgr._resolve_node_connector("document_parsing", "entity_summarizer")
        gext_conn, gext_model = mgr._resolve_node_connector("document_parsing", "graph_extractor")

        assert sum_conn is openai
        assert sum_model == "gpt-5-nano"
        assert esum_conn is google
        assert esum_model == "gemini-2.5-flash-lite"
        assert gext_conn is google

    def test_empty_provider_falls_back_to_default(self):
        registry = ConnectorRegistry()
        default_conn = _make_mock_connector("OpenAI")
        registry.register(default_conn)

        config = ZForgeConfig(
            llm_nodes={
                "world_generation": {
                    "summarizer": LlmNodeConfig(provider="", model=""),
                }
            }
        )
        mgr = self._make_manager(config, registry)

        connector, model = mgr._resolve_node_connector("world_generation", "summarizer")
        assert connector is default_conn
        assert model is None
