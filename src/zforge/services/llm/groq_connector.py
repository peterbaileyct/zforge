"""Groq chat connector.

Uses langchain-groq's ChatGroq to provide remote chat inference
for LangGraph agent nodes.

Implements: src/zforge/services/llm/groq_connector.py per
docs/LLM Abstraction Layer.md.
"""

from __future__ import annotations

import logging

import keyring
from langchain_core.language_models import BaseChatModel

from zforge.services.llm.llm_connector import LlmConnector

log = logging.getLogger(__name__)

_KEYRING_SERVICE = "zforge"
_KEYRING_KEY = "llm.groq.api_key"

_DEFAULT_MODEL = "llama-3.3-70b-versatile"

# Fallback list used when the API key is absent or the models endpoint fails.
# Filtered to text chat-completion models only (as of March 2026).
_FALLBACK_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.3-70b-specdec",
    "llama-3.1-8b-instant",
    "llama-3.1-70b-versatile",
    "gemma2-9b-it",
    "qwen-qwq-32b",
    "deepseek-r1-distill-llama-70b",
    "deepseek-r1-distill-qwen-32b",
    "mistral-saba-24b",
]

# Model ID substrings that indicate non-chat-completion models.
_EXCLUDE_SUBSTRINGS = (
    "whisper",
    "tts",
    "embed",
    "guard",
    "vision",
)


class GroqConnector(LlmConnector):
    """LlmConnector backed by the Groq API via langchain-groq."""

    def __init__(self, context_size: int = 128_000) -> None:
        self._context_size = context_size
        self._api_key: str | None = None
        self._models: dict[str, BaseChatModel] = {}
        self._cached_models: list[str] | None = None

    def get_name(self) -> str:
        return "Groq"

    def get_config_keys(self) -> list[str]:
        return ["api_key"]

    def get_available_models(self) -> list[str]:
        """Return available chat models, fetching from the Groq API on first call.

        Falls back to ``_FALLBACK_MODELS`` when the API key is absent or the
        models endpoint raises an error.
        """
        if self._cached_models is not None:
            return list(self._cached_models)
        if not self._api_key:
            return list(_FALLBACK_MODELS)
        try:
            import groq as _groq

            client = _groq.Groq(api_key=self._api_key)
            all_models = [m.id for m in client.models.list().data]
            chat_models = [
                mid for mid in all_models
                if not any(excl in mid for excl in _EXCLUDE_SUBSTRINGS)
            ]
            chat_models.sort()
            if chat_models:
                self._cached_models = chat_models
                log.info("GroqConnector: fetched %d chat models from API", len(chat_models))
                return list(self._cached_models)
        except Exception:
            log.warning("GroqConnector: failed to fetch models from API, using fallback list")
        self._cached_models = list(_FALLBACK_MODELS)
        return list(self._cached_models)

    def load_from_keyring(self) -> None:
        """Load API key from the platform keychain."""
        self._api_key = keyring.get_password(_KEYRING_SERVICE, _KEYRING_KEY)

    def set_api_key(self, api_key: str) -> None:
        """Set the API key programmatically and persist to keyring.

        Clears the cached model list so the next call to ``get_available_models``
        re-fetches with the updated key.
        """
        self._api_key = api_key
        self._cached_models = None
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_KEY, api_key)

    def validate(self) -> bool:
        if not self._api_key:
            log.warning("Groq API key is not configured")
            return False
        return True

    def get_context_size(self) -> int:
        return self._context_size

    def get_model(self, model_name: str | None = None) -> BaseChatModel:
        """Return a ChatGroq instance for the given model (cached)."""
        name = model_name or _DEFAULT_MODEL
        if name in self._models:
            return self._models[name]

        from langchain_groq import ChatGroq

        log.info("GroqConnector.get_model: creating ChatGroq for %s", name)
        model = ChatGroq(model=name, api_key=self._api_key)  # type: ignore[arg-type]
        self._models[name] = model
        return model
