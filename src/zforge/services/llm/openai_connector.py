"""OpenAI chat connector.

Uses langchain-openai's ChatOpenAI to provide remote chat inference
for LangGraph agent nodes.

Implements: src/zforge/services/llm/openai_connector.py per
docs/LLM Abstraction Layer.md.
"""

from __future__ import annotations

import logging

import keyring
from langchain_core.language_models import BaseChatModel

from zforge.services.llm.llm_connector import LlmConnector

log = logging.getLogger(__name__)

_KEYRING_SERVICE = "zforge"
_KEYRING_KEY = "llm.openai.api_key"

_DEFAULT_MODEL = "gpt-5-nano"

# Fallback list used when the API key is absent or the models endpoint fails.
# Filtered to text chat-completion models only; non-chat models (image, audio,
# tts, realtime, moderation, codex, sora, etc.) are excluded.
_FALLBACK_MODELS = [
    "gpt-5.4",
    "gpt-5.4-pro",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-5",
    "gpt-4.1",
    "gpt-4o",
    "gpt-4o-mini",
]

# Model ID substrings that indicate non-chat-completion models.
_EXCLUDE_SUBSTRINGS = (
    "tts", "transcribe", "audio", "realtime", "image", "search",
    "moderation", "embedding", "dall-e", "whisper", "sora", "babbage",
    "davinci", "codex", "deep-research", "computer-use", "oss",
    "chat-latest",
)


class OpenAiConnector(LlmConnector):
    """LlmConnector backed by the OpenAI API via langchain-openai."""

    def __init__(self, context_size: int = 128_000) -> None:
        self._context_size = context_size
        self._api_key: str | None = None
        self._models: dict[str, BaseChatModel] = {}
        self._cached_models: list[str] | None = None

    def get_name(self) -> str:
        return "OpenAI"

    def get_config_keys(self) -> list[str]:
        return ["api_key"]

    def get_available_models(self) -> list[str]:
        """Return available chat models, fetching from the API on first call.

        Falls back to ``_FALLBACK_MODELS`` when the API key is absent or the
        models endpoint raises an error.
        """
        if self._cached_models is not None:
            return list(self._cached_models)
        if not self._api_key:
            return list(_FALLBACK_MODELS)
        try:
            import openai as _openai

            client = _openai.OpenAI(api_key=self._api_key)
            all_models = [m.id for m in client.models.list().data]
            chat_models = [
                mid for mid in all_models
                if (mid.startswith("gpt-") or (len(mid) > 1 and mid[0] == "o" and mid[1].isdigit()))
                and not any(excl in mid for excl in _EXCLUDE_SUBSTRINGS)
            ]
            chat_models.sort()
            if chat_models:
                self._cached_models = chat_models
                log.info("OpenAiConnector: fetched %d chat models from API", len(chat_models))
                return list(self._cached_models)
        except Exception:
            log.warning("OpenAiConnector: failed to fetch models from API, using fallback list")
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
            log.warning("OpenAI API key is not configured")
            return False
        return True

    def get_context_size(self) -> int:
        return self._context_size

    def get_model(self, model_name: str | None = None) -> BaseChatModel:
        """Return a ChatOpenAI instance for the given model (cached)."""
        name = model_name or _DEFAULT_MODEL
        if name in self._models:
            return self._models[name]

        from langchain_openai import ChatOpenAI

        log.info("OpenAiConnector.get_model: creating ChatOpenAI for %s", name)
        model = ChatOpenAI(model=name, api_key=self._api_key)  # type: ignore[arg-type]
        self._models[name] = model
        return model
