"""LlamaCpp embedding connector.

Uses llama-cpp-python via LangChain's LlamaCppEmbeddings to produce
local embeddings for Z-Bundle vector stores.

Implements: src/zforge/services/embedding/llama_cpp_embedding_connector.py per
docs/Local LLM Execution.md.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from langchain_core.embeddings import Embeddings

from zforge.services.embedding.embedding_connector import EmbeddingConnector

log = logging.getLogger(__name__)


class LlamaCppEmbeddingConnector(EmbeddingConnector):
    """EmbeddingConnector backed by a local GGUF model via llama-cpp-python."""

    def __init__(
        self,
        model_path: str,
        context_size: int = 512,
        gpu_layers: int = 0,
    ) -> None:
        self._model_path = model_path
        self._context_size = context_size
        self._gpu_layers = gpu_layers
        self._resolved_path: Path | None = None
        self._embeddings: Embeddings | None = None

    def _resolve_path(self) -> Path:
        """Resolve the model path relative to sandboxed storage."""
        if self._resolved_path is not None:
            return self._resolved_path
        path = Path(self._model_path)
        if not path.is_absolute():
            from platformdirs import user_data_dir

            base = Path(user_data_dir("zforge"))
            path = base / path
        self._resolved_path = path
        return path

    def validate(self) -> bool:
        """Check that the GGUF model file exists at the resolved path."""
        if not self._model_path:
            log.warning("Embedding model path is not configured")
            return False
        path = self._resolve_path()
        exists = path.exists() and path.is_file()
        if not exists:
            log.warning("Embedding model not found at %s", path)
        return exists

    def get_context_size(self) -> int:
        """Return the configured context window size in tokens."""
        return self._context_size

    def get_embeddings(self) -> Embeddings:
        """Return a cached LangChain LlamaCppEmbeddings instance.

        The instance is created on the first call and reused thereafter.
        Constructing a new LlamaCppEmbeddings on every call causes repeated
        model load/unload cycles that exhaust llama.cpp's Metal command queue
        on macOS and produce ``llama_decode returned -1`` errors.
        See docs/Parsing Documents to Z-Bundles.md § Embedding repeated
        model construction pitfall.
        """
        if self._embeddings is not None:
            return self._embeddings
        from langchain_community.embeddings import LlamaCppEmbeddings

        path = self._resolve_path()
        self._embeddings = LlamaCppEmbeddings(
            model_path=str(path),
            n_ctx=self._context_size,
            n_gpu_layers=self._gpu_layers,
            verbose=False,
        )
        return self._embeddings

    def model_identity(self) -> dict:
        """Return model basename and file size for KVP storage."""
        path = self._resolve_path()
        return {
            "embedding_model_name": path.name,
            "embedding_model_size_bytes": path.stat().st_size if path.exists() else 0,
        }
