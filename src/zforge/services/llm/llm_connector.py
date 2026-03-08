"""LLM Connector abstract base class.

Wraps a LangChain BaseChatModel for use with LangGraph orchestration.
Implements: src/zforge/services/llm/llm_connector.py per docs/LLM Abstraction Layer.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from langchain_core.language_models import BaseChatModel


class LlmConnector(ABC):
    """Abstract base class for LLM connectors."""

    @abstractmethod
    def get_name(self) -> str:
        """Display name of this connector (e.g., 'Local LLM (llama.cpp)')."""

    @abstractmethod
    def get_config_keys(self) -> list[str]:
        """Names of required configuration values (e.g., ['api_key'])."""

    @abstractmethod
    def load_from_keyring(self) -> None:
        """Load credentials from keyring into connector state."""

    @abstractmethod
    def validate(self) -> bool:
        """Return True if credentials are present and valid."""

    @abstractmethod
    def get_model(self) -> BaseChatModel:
        """Return a configured LangChain chat model instance."""

    @abstractmethod
    def get_context_size(self) -> int:
        """Return the configured context window size in tokens."""
