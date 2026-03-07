"""Gameplay Screen.

Scrolling text output, choice buttons, text input, save/restore.
Implements: src/zforge/ui/screens/gameplay_screen.py per docs/User Experience.md.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import toga
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN, LEFT, RIGHT, ROW

if TYPE_CHECKING:
    from zforge.app_state import AppState
    from zforge.models.results import Experience


class GameplayScreen:
    """Interactive fiction gameplay interface."""

    def __init__(
        self,
        app: toga.App,
        app_state: AppState,
        experience: Experience | None = None,
        resume: bool = False,
    ) -> None:
        self._app = app
        self._state = app_state
        self._current_experience = experience
        self._resume = resume
        self._box = toga.Box(style=Pack(direction=COLUMN, padding=10))
        self._transcript = toga.MultilineTextInput(
            readonly=True,
            style=Pack(flex=1, padding=5, font_family="monospace"),
        )
        self._choices_box = toga.Box(
            style=Pack(direction=COLUMN, padding=5)
        )
        self._build_ui()
        asyncio.ensure_future(self._initialize())

    def _build_ui(self) -> None:
        # Transcript output area (wraps and self-scrolls)
        self._box.add(self._transcript)

        # Choice buttons
        self._box.add(self._choices_box)

        # Input row
        input_row = toga.Box(style=Pack(direction=ROW, padding_top=5))
        self._text_input = toga.TextInput(
            placeholder="Enter choice number or tap above",
            style=Pack(flex=1),
            on_confirm=self._on_submit_input,
        )
        input_row.add(self._text_input)
        submit_btn = toga.Button(
            "↵",
            on_press=self._on_submit_input,
            style=Pack(padding_left=5, width=40),
        )
        input_row.add(submit_btn)
        self._box.add(input_row)

        # Menu buttons
        menu_row = toga.Box(style=Pack(direction=ROW, padding_top=5))
        save_btn = toga.Button(
            "Save", on_press=self._on_save, style=Pack(padding=5)
        )
        menu_row.add(save_btn)
        restore_btn = toga.Button(
            "Restore", on_press=self._on_restore, style=Pack(padding=5)
        )
        menu_row.add(restore_btn)
        home_btn = toga.Button(
            "Home", on_press=self._on_home, style=Pack(padding=5)
        )
        menu_row.add(home_btn)
        self._box.add(menu_row)

    async def _initialize(self) -> None:
        """Load and start (or resume) the current experience."""
        if_engine = self._state.if_engine_connector
        mgr = self._state.zforge_manager
        exp = self._current_experience
        if if_engine is None or mgr is None or exp is None:
            self._add_game_text("No experience selected.")
            return

        compiled_data = mgr.experience_manager.load_experience(
            exp.zworld_id, exp.name
        )
        if compiled_data is None:
            self._add_game_text("Could not load experience data.")
            return

        if self._resume and mgr.experience_manager.has_saved_progress(
            exp.zworld_id, exp.name
        ):
            saved = mgr.experience_manager.load_progress(exp.zworld_id, exp.name)
            await if_engine.start_experience(compiled_data)
            result = await if_engine.restore_state(saved)
            self._add_game_text(result.text)
            self._show_choices(result.choices)
        else:
            text = await if_engine.start_experience(compiled_data)
            state_choices = await if_engine.get_current_choices() if hasattr(if_engine, "get_current_choices") else []
            self._add_game_text(text)
            self._show_choices(state_choices or None)

    def _add_game_text(self, text: str) -> None:
        """Append game output text to the transcript."""
        self._transcript.value = (self._transcript.value or "") + text.rstrip("\n") + "\n"

    def _add_player_text(self, text: str) -> None:
        """Append player input text to the transcript (prefixed with '>>')."""
        self._transcript.value = (self._transcript.value or "") + f">> {text}\n"

    def _show_choices(self, choices: list[str] | None) -> None:
        """Display choice buttons."""
        self._choices_box.clear()
        if not choices:
            return
        for i, choice_text in enumerate(choices):
            btn = toga.Button(
                f"{i + 1}. {choice_text}",
                on_press=lambda w, idx=i: asyncio.ensure_future(
                    self._select_choice(idx)
                ),
                style=Pack(padding=2, text_align=LEFT),
            )
            self._choices_box.add(btn)

    async def _select_choice(self, index: int) -> None:
        """Handle a choice selection."""
        if_engine = self._state.if_engine_connector
        if if_engine is None:
            return

        # Show player's choice in output
        choices = await if_engine.get_current_choices() if hasattr(if_engine, 'get_current_choices') else []
        if index < len(choices):
            self._add_player_text(choices[index])

        result = await if_engine.take_action(str(index))
        self._add_game_text(result.text)
        self._show_choices(result.choices)

        if result.is_complete:
            self._add_game_text("\n— Experience Complete —")
            self._choices_box.clear()

    def _on_submit_input(self, widget) -> None:
        text = self._text_input.value.strip()
        if text:
            self._text_input.value = ""
            try:
                index = int(text) - 1
                asyncio.ensure_future(self._select_choice(index))
            except ValueError:
                pass

    def _on_save(self, widget) -> None:
        asyncio.ensure_future(self._do_save())

    async def _do_save(self) -> None:
        if_engine = self._state.if_engine_connector
        mgr = self._state.zforge_manager
        exp = self._current_experience
        if if_engine is None or mgr is None or exp is None:
            return
        state_bytes = await if_engine.save_state()
        mgr.experience_manager.save_progress(exp.zworld_id, exp.name, state_bytes)
        self._add_game_text("Progress saved.")

    def _on_restore(self, widget) -> None:
        asyncio.ensure_future(self._do_restore())

    async def _do_restore(self) -> None:
        if_engine = self._state.if_engine_connector
        mgr = self._state.zforge_manager
        exp = self._current_experience
        if if_engine is None or mgr is None or exp is None:
            return
        state_bytes = mgr.experience_manager.load_progress(exp.zworld_id, exp.name)
        if state_bytes:
            result = await if_engine.restore_state(state_bytes)
            self._add_game_text(result.text)
            self._show_choices(result.choices)
        else:
            self._add_game_text("No saved progress found.")

    def _on_home(self, widget) -> None:
        from zforge.ui.screens.home_screen import HomeScreen
        screen = HomeScreen(self._app, self._state)
        screen.refresh()
        self._app.main_window.content = screen.box

    @property
    def box(self) -> toga.Box:
        return self._box
