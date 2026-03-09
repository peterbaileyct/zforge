"""Google (Gemini) chat connector.

Uses langchain-google-genai's ChatGoogleGenerativeAI to provide
remote chat inference for LangGraph agent nodes.

Implements: src/zforge/services/llm/google_connector.py per
docs/LLM Abstraction Layer.md.
"""

from __future__ import annotations

import logging

import keyring
from langchain_core.language_models import BaseChatModel

from zforge.services.llm.llm_connector import LlmConnector

log = logging.getLogger(__name__)

_KEYRING_SERVICE = "zforge"
_KEYRING_KEY = "llm.google.api_key"

_DEFAULT_MODEL = "gemini-2.5-flash"
_KNOWN_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
]


class GoogleConnector(LlmConnector):
    """LlmConnector backed by the Google Gemini API."""

    def __init__(self, context_size: int = 1_000_000) -> None:
        self._context_size = context_size
        self._api_key: str | None = None
        self._models: dict[str, BaseChatModel] = {}

    def get_name(self) -> str:
        return "Google"

    def get_config_keys(self) -> list[str]:
        return ["api_key"]

    def get_available_models(self) -> list[str]:
        return list(_KNOWN_MODELS)

    def load_from_keyring(self) -> None:
        self._api_key = keyring.get_password(_KEYRING_SERVICE, _KEYRING_KEY)

    def set_api_key(self, api_key: str) -> None:
        self._api_key = api_key
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_KEY, api_key)

    def validate(self) -> bool:
        if not self._api_key:
            log.warning("Google API key is not configured")
            return False
        return True

    def get_context_size(self) -> int:
        return self._context_size

    def get_model(self, model_name: str | None = None) -> BaseChatModel:
        """Return a ChatGoogleGenerativeAI instance (cached)."""
        name = model_name or _DEFAULT_MODEL
        if name in self._models:
            return self._models[name]

        from langchain_google_genai import ChatGoogleGenerativeAI

        log.info("GoogleConnector.get_model: creating model for %s", name)
        model = ChatGoogleGenerativeAI(
            model=name, google_api_key=self._api_key  # type: ignore[arg-type]
        )
        self._models[name] = model
        return model
