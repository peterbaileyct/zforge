"""LLM Connector Registry.

Singleton mapping connector display names to LlmConnector instances.
Populated at application startup and used to resolve per-node
LLM configuration in LangGraph process graphs.

Implements: src/zforge/services/llm/connector_registry.py per
docs/LLM Abstraction Layer.md.
"""

from __future__ import annotations

import logging

from zforge.services.llm.llm_connector import LlmConnector

log = logging.getLogger(__name__)


class ConnectorRegistry:
    """Maps human-readable connector names to LlmConnector instances."""

    def __init__(self) -> None:
        self._connectors: dict[str, LlmConnector] = {}
        self._default_name: str | None = None

    def register(self, connector: LlmConnector) -> None:
        """Register a connector by its display name."""
        name = connector.get_name()
        log.info("ConnectorRegistry: registering %r", name)
        self._connectors[name] = connector
        if self._default_name is None:
            self._default_name = name

    def get(self, name: str) -> LlmConnector | None:
        """Return the connector with the given name, or None."""
        return self._connectors.get(name)

    def get_default(self) -> LlmConnector:
        """Return the default connector.

        Raises
        ------
        RuntimeError
            If no connectors have been registered.
        """
        if self._default_name is None:
            raise RuntimeError("No connectors registered")
        return self._connectors[self._default_name]

    def set_default(self, name: str) -> None:
        """Set the named connector as the default."""
        if name not in self._connectors:
            raise KeyError(f"Unknown connector: {name!r}")
        self._default_name = name

    def list_names(self) -> list[str]:
        """Return all registered connector names."""
        return list(self._connectors.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._connectors

    def __len__(self) -> int:
        return len(self._connectors)
