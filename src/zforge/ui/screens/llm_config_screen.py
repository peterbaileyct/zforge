"""LLM Configuration Screen.

Prompts user for LLM credentials, validates, and stores to keyring.
Implements: src/zforge/ui/screens/llm_config_screen.py per docs/User Experience.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import toga
from toga.style import Pack
from toga.style.pack import COLUMN

if TYPE_CHECKING:
    from zforge.app_state import AppState


class LlmConfigScreen:
    """Screen for entering and validating LLM credentials."""

    def __init__(
        self,
        app: toga.App,
        app_state: AppState,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        self._app = app
        self._state = app_state
        self._on_done = on_done
        self._inputs: dict[str, toga.TextInput] = {}
        self._box = toga.Box(style=Pack(direction=COLUMN, padding=10))
        self._status_label = toga.Label("", style=Pack(padding_top=10))
        self._build_ui()

    def _build_ui(self) -> None:
        connector = self._state.llm_connector
        if connector is None:
            return

        name = connector.get_name()
        title = toga.Label(
            f"{name} Configuration",
            style=Pack(padding_bottom=10, font_size=16, font_weight="bold"),
        )
        self._box.add(title)

        info = toga.Label(
            f"{name} configuration has not been provided or is invalid. "
            "Please enter the required credentials below.",
            style=Pack(padding_bottom=10),
        )
        self._box.add(info)

        for key in connector.get_config_keys():
            label = toga.Label(
                f"{key.replace('_', ' ').title()}:",
                style=Pack(padding_top=5),
            )
            self._box.add(label)
            text_input = toga.TextInput(style=Pack(padding_bottom=5, flex=1))
            self._inputs[key] = text_input
            self._box.add(text_input)

        submit_btn = toga.Button(
            "Submit",
            on_press=self._on_submit,
            style=Pack(padding_top=10),
        )
        self._box.add(submit_btn)
        self._box.add(self._status_label)

    def _on_submit(self, widget) -> None:
        connector = self._state.llm_connector
        if connector is None:
            return

        # For OpenAI, save the API key
        from zforge.services.llm.openai_connector import OpenAiConnector

        if isinstance(connector, OpenAiConnector):
            api_key = self._inputs.get("api_key")
            if api_key and api_key.value:
                connector.save_to_keyring(api_key.value.strip())

        if connector.validate():
            self._status_label.text = "Credentials valid! Continuing..."
            if self._on_done:
                self._on_done()
        else:
            self._status_label.text = (
                "Credentials invalid. Please double-check and try again."
            )

    @property
    def box(self) -> toga.Box:
        return self._box
