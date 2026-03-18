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
    def get_available_models(self) -> list[str]:
        """Return the list of models this connector can serve."""

    @abstractmethod
    def load_from_keyring(self) -> None:
        """Load credentials from keyring into connector state."""

    @abstractmethod
    def validate(self) -> bool:
        """Return True if credentials are present and valid."""

    @abstractmethod
    def get_model(self, model_name: str | None = None) -> BaseChatModel:
        """Return a configured LangChain chat model instance.

        Parameters
        ----------
        model_name:
            Specific model to use.  When *None*, the connector's default
            model is returned.
        """

    @abstractmethod
    def get_context_size(self) -> int:
        """Return the configured context window size in tokens."""

    @abstractmethod
    def set_api_key(self, api_key: str) -> None:
        """Store an API key for this connector.

        For connectors that do not require an API key (e.g. local models),
        this should be a no-op.
        """
