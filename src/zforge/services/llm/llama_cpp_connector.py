"""LlamaCpp chat connector.

Uses llama-cpp-python via LangChain's ChatLlamaCpp to provide
local chat inference for all LangGraph agent nodes.

Implements: src/zforge/services/llm/llama_cpp_connector.py per
docs/Local LLM Execution.md.
"""

from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.language_models import BaseChatModel

from zforge.services.llm.llm_connector import LlmConnector

log = logging.getLogger(__name__)


class LlamaCppConnector(LlmConnector):
    """LlmConnector backed by a local GGUF model via llama-cpp-python."""

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
        self._model: BaseChatModel | None = None

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

    def get_name(self) -> str:
        return "Local LLM (llama.cpp)"

    def get_config_keys(self) -> list[str]:
        return ["model_path"]

    def get_available_models(self) -> list[str]:
        """Return the configured model path as the only available model."""
        if self._model_path:
            return [self._model_path]
        return []

    def load_from_keyring(self) -> None:
        # No secrets — model path comes from config, not keyring.
        pass

    def validate(self) -> bool:
        """Check that the GGUF model file exists at the resolved path."""
        if not self._model_path:
            log.warning("Chat model path is not configured")
            return False
        path = self._resolve_path()
        exists = path.exists() and path.is_file()
        if not exists:
            log.warning("Chat model not found at %s", path)
        return exists

    def get_context_size(self) -> int:
        """Return the configured context window size in tokens."""
        return self._context_size

    def get_model(self, model_name: str | None = None) -> BaseChatModel:
        """Return a LangChain ChatLlamaCpp instance (cached after first load).

        The *model_name* parameter is accepted for ABC compliance but
        ignored — the local connector always uses the configured GGUF path.
        """
        if self._model is not None:
            return self._model
        from langchain_community.chat_models import ChatLlamaCpp

        path = self._resolve_path()
        log.info("LlamaCppConnector.get_model: loading model from %s", path)
        self._model = ChatLlamaCpp(
            model_path=str(path),
            n_ctx=self._context_size,
            n_gpu_layers=self._gpu_layers,
            verbose=False,
        )
        log.info("LlamaCppConnector.get_model: model loaded")
        return self._model
