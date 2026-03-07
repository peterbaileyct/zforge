"""OpenAI LLM Connector implementation.

Implements: src/zforge/services/llm/openai_connector.py per
docs/LLM Abstraction Layer.md.
"""

from __future__ import annotations

import keyring
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from zforge.services.llm.llm_connector import LlmConnector


_SERVICE_NAME = "zforge"
_KEYRING_KEY = "openai_api_key"


class OpenAiConnector(LlmConnector):
    """LLM connector for OpenAI via LangChain ChatOpenAI."""

    def __init__(self) -> None:
        self._api_key: str | None = None

    def get_name(self) -> str:
        return "OpenAI"

    def get_config_keys(self) -> list[str]:
        return ["api_key"]

    def load_from_keyring(self) -> None:
        self._api_key = keyring.get_password(_SERVICE_NAME, _KEYRING_KEY)

    def save_to_keyring(self, api_key: str) -> None:
        """Store the API key in the platform keychain."""
        self._api_key = api_key
        keyring.set_password(_SERVICE_NAME, _KEYRING_KEY, api_key)

    def validate(self) -> bool:
        """Check that credentials are present and make a lightweight API call."""
        if not self._api_key:
            return False
        try:
            model = ChatOpenAI(api_key=self._api_key, model="gpt-4o-mini")
            model.invoke("ping")
            return True
        except Exception:
            return False

    def get_model(self) -> BaseChatModel:
        if not self._api_key:
            raise RuntimeError("OpenAI API key not configured")
        return ChatOpenAI(api_key=self._api_key, model="gpt-4o")
