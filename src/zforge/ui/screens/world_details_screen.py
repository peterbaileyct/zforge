"""World Details Screen.

Displays world title, summary, and a question/answer interface (stub).
Shows an embedding mismatch warning when the configured model differs
from what was used to encode the bundle.

Implements: src/zforge/ui/screens/world_details_screen.py per
docs/User Experience.md — World Details Screen section.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

if TYPE_CHECKING:
    from zforge.app_state import AppState


class WorldDetailsScreen:
    """Read-only world details with a stub Q&A interface."""

    def __init__(
        self,
        app: toga.App,
        app_state: AppState,
        slug: str,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        self._app = app
        self._state = app_state
        self._slug = slug
        self._on_done = on_done
        self._box = toga.Box(style=Pack(direction=COLUMN, padding=10))
        self._build_ui()

    def _build_ui(self) -> None:
        mgr = self._state.zforge_manager
        if mgr is None:
            self._box.add(toga.Label("Error: not initialized."))
            return

        zworld = mgr.zworld_manager.read(self._slug)
        if zworld is None:
            self._box.add(toga.Label(f"World '{self._slug}' not found."))
            self._add_back_button()
            return

        # Embedding mismatch warning
        if mgr.zworld_manager.check_embedding_mismatch(self._slug):
            warning = toga.Label(
                "⚠ This world was encoded with a different embedding model. "
                "Search quality may be degraded until it is re-encoded.",
                style=Pack(
                    padding=8,
                    font_style="italic",
                    color="#b8860b",
                ),
            )
            self._box.add(warning)

        # Title
        title = toga.Label(
            zworld.title,
            style=Pack(padding_bottom=10, font_size=20, font_weight="bold"),
        )
        self._box.add(title)

        # Scrollable read-only summary
        summary = toga.MultilineTextInput(
            readonly=True,
            value=zworld.summary,
            style=Pack(flex=1, padding_bottom=10),
        )
        self._box.add(summary)

        # Question input row
        question_row = toga.Box(style=Pack(direction=ROW, padding_bottom=5))
        self._question_input = toga.TextInput(
            placeholder="Ask a question about this world\u2026",
            style=Pack(flex=1),
        )
        question_row.add(self._question_input)

        ask_btn = toga.Button(
            "Ask",
            on_press=self._on_ask,
            style=Pack(padding_left=5),
        )
        question_row.add(ask_btn)
        self._box.add(question_row)

        # Read-only answer area
        self._answer_area = toga.MultilineTextInput(
            readonly=True,
            style=Pack(flex=1, padding_bottom=10),
        )
        self._box.add(self._answer_area)

        self._add_back_button()

    def _add_back_button(self) -> None:
        back_btn = toga.Button(
            "Back",
            on_press=self._on_back,
            style=Pack(padding_top=5),
        )
        self._box.add(back_btn)

    def _on_ask(self, widget) -> None:
        self._answer_area.value = "TODO"

    def _on_back(self, widget) -> None:
        if self._on_done:
            self._on_done()

    @property
    def box(self) -> toga.Box:
        return self._box
