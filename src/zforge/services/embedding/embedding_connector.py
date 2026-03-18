"""EmbeddingConnector abstract base class.

Defines the interface for embedding model connectors used by ZWorldManager
to encode Z-Bundle vector stores.

Implements: src/zforge/services/embedding/embedding_connector.py per
docs/Local LLM Execution.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from langchain_core.embeddings import Embeddings


class EmbeddingConnector(ABC):
    """ABC for embedding model connectors."""

    @abstractmethod
    def validate(self) -> bool:
        """Check that the embedding model is available and configured."""

    @abstractmethod
    def get_embeddings(self) -> Embeddings:
        """Return a LangChain Embeddings instance for the configured model."""

    @abstractmethod
    def get_context_size(self) -> int:
        """Return the maximum number of tokens the embedding model can process.

        Callers should truncate input text to roughly ``get_context_size() * 4``
        characters (≈4 chars per token for English prose) before embedding to
        prevent llama_decode / tokeniser overflow errors.
        """

    @abstractmethod
    def model_identity(self) -> dict[str, str | int]:
        """Return embedding model metadata for Z-Bundle KVP storage.

        Returns a dict with keys:
            - embedding_model_name: basename of the model file
            - embedding_model_size_bytes: file size in bytes
        """
