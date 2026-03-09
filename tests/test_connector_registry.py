"""Tests for ConnectorRegistry."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from zforge.services.llm.connector_registry import ConnectorRegistry
from zforge.services.llm.llm_connector import LlmConnector


def _make_mock_connector(name: str) -> LlmConnector:
    """Create a mock LlmConnector with the given display name."""
    connector = MagicMock(spec=LlmConnector)
    connector.get_name.return_value = name
    return connector


class TestConnectorRegistry:
    def test_register_and_get(self):
        registry = ConnectorRegistry()
        c = _make_mock_connector("OpenAI")
        registry.register(c)

        assert registry.get("OpenAI") is c

    def test_get_unknown_returns_none(self):
        registry = ConnectorRegistry()
        assert registry.get("NonExistent") is None

    def test_list_names(self):
        registry = ConnectorRegistry()
        registry.register(_make_mock_connector("OpenAI"))
        registry.register(_make_mock_connector("Google"))
        registry.register(_make_mock_connector("Anthropic"))

        names = registry.list_names()
        assert set(names) == {"OpenAI", "Google", "Anthropic"}

    def test_default_is_first_registered(self):
        registry = ConnectorRegistry()
        first = _make_mock_connector("First")
        second = _make_mock_connector("Second")
        registry.register(first)
        registry.register(second)

        assert registry.get_default() is first

    def test_set_default(self):
        registry = ConnectorRegistry()
        first = _make_mock_connector("First")
        second = _make_mock_connector("Second")
        registry.register(first)
        registry.register(second)
        registry.set_default("Second")

        assert registry.get_default() is second

    def test_set_default_unknown_raises(self):
        registry = ConnectorRegistry()
        registry.register(_make_mock_connector("OpenAI"))

        with pytest.raises(KeyError):
            registry.set_default("NonExistent")

    def test_get_default_empty_raises(self):
        registry = ConnectorRegistry()

        with pytest.raises(RuntimeError):
            registry.get_default()

    def test_contains(self):
        registry = ConnectorRegistry()
        registry.register(_make_mock_connector("OpenAI"))

        assert "OpenAI" in registry
        assert "Google" not in registry

    def test_len(self):
        registry = ConnectorRegistry()
        assert len(registry) == 0
        registry.register(_make_mock_connector("A"))
        registry.register(_make_mock_connector("B"))
        assert len(registry) == 2
