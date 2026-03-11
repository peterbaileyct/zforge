"""Create World Screen.

Text input for world description, progress display during LangGraph run.
Implements: src/zforge/ui/screens/create_world_screen.py per
docs/User Experience.md and docs/World Generation.md.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Callable

import toga
from toga.style import Pack
from toga.style.pack import COLUMN

if TYPE_CHECKING:
    from zforge.app_state import AppState


class CreateWorldScreen:
    """Screen for creating a new ZWorld from a text description."""

    def __init__(
        self,
        app: toga.App,
        app_state: AppState,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        self._app = app
        self._state = app_state
        self._on_done = on_done
        self._box = toga.Box(style=Pack(direction=COLUMN, padding=10))
        self._progress_label = toga.Label("", style=Pack(padding_top=10))
        self._build_ui()

    def _build_ui(self) -> None:
        title = toga.Label(
            "Create World",
            style=Pack(padding_bottom=10, font_size=16, font_weight="bold"),
        )
        self._box.add(title)

        instructions = toga.Label(
            "Enter a description of your fictional world below:",
            style=Pack(padding_bottom=5),
        )
        self._box.add(instructions)

        self._text_input = toga.MultilineTextInput(
            style=Pack(flex=1, padding_bottom=10),
            placeholder="Describe characters, locations, relationships, and events...",
        )
        self._box.add(self._text_input)

        self._create_btn = toga.Button(
            "Create World",
            on_press=self._on_create,
            style=Pack(padding_bottom=5),
        )
        self._box.add(self._create_btn)

        back_btn = toga.Button(
            "Back",
            on_press=self._on_back,
            style=Pack(padding_bottom=5),
        )
        self._box.add(back_btn)
        self._box.add(self._progress_label)

    def _on_create(self, widget) -> None:
        description = self._text_input.value.strip()
        if not description:
            self._progress_label.text = "Please enter a world description."
            return

        self._create_btn.enabled = False
        self._progress_label.text = "Starting world creation..."
        asyncio.ensure_future(self._run_creation(description))

    async def _confirm_duplicate(self, conflicting_slug: str) -> str:
        """Show a dialog asking whether to overwrite an existing world.

        Returns ``"overwrite"`` or ``"cancel"``.
        """
        confirmed = await self._app.main_window.question_dialog(
            "Duplicate World",
            f"A world with slug '{conflicting_slug}' already exists.\n\n"
            "Would you like to overwrite it?",
        )
        return "overwrite" if confirmed else "cancel"

    async def _run_creation(self, description: str) -> None:
        mgr = self._state.zforge_manager
        if mgr is None:
            self._progress_label.text = "Error: Manager not initialized."
            return

        def on_update(msg: str) -> None:
            self._progress_label.text = msg

        try:
            zworld = await mgr.start_world_creation(
                input_text=description,
                on_progress=on_update,
                on_confirm_duplicate=self._confirm_duplicate,
            )

            if zworld is not None:
                self._progress_label.text = "World created successfully!"
                if self._on_done:
                    self._on_done()
            else:
                self._progress_label.text = "World creation cancelled or failed."
                self._create_btn.enabled = True
        except Exception as exc:
            self._progress_label.text = f"Failed: {exc}"
            self._create_btn.enabled = True

    def _on_back(self, widget) -> None:
        if self._on_done:
            self._on_done()

    @property
    def box(self) -> toga.Box:
        return self._box
