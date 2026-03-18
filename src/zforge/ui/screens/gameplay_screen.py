"""Gameplay Screen.

Scrolling text output, choice buttons, text input, save/restore.
Implements: src/zforge/ui/screens/gameplay_screen.py per docs/User Experience.md.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import flet as ft

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from zforge.app_state import AppState
    from zforge.models.results import Experience


class GameplayScreen:
    """Interactive fiction gameplay interface."""

    def __init__(
        self,
        page: ft.Page,
        app_state: AppState,
        experience: Experience | None = None,
        resume: bool = False,
    ) -> None:
        self._page = page
        self._state = app_state
        self._current_experience = experience
        self._resume = resume

    def build(self) -> ft.Control:
        self._transcript = ft.TextField(
            multiline=True,
            read_only=True,
            expand=True,
            text_style=ft.TextStyle(font_family="monospace"),
        )
        self._choices_box = ft.Column([], spacing=2)

        self._text_input = ft.TextField(
            hint_text="Enter choice number or tap above",
            expand=True,
            on_submit=lambda _: self._on_submit_input(),
        )

        input_row: list[ft.Control] = [
            self._text_input,
            ft.ElevatedButton("↵", on_click=lambda _: self._on_submit_input(), width=50),
        ]
        nav_row: list[ft.Control] = [
            ft.ElevatedButton("Save", on_click=self._on_save),
            ft.ElevatedButton("Restore", on_click=self._on_restore),
            ft.ElevatedButton("Home", on_click=self._on_home),
        ]
        root_controls: list[ft.Control] = [
            self._transcript,
            self._choices_box,
            ft.Row(input_row),
            ft.Row(nav_row),
        ]
        root = ft.Column(
            root_controls,
            spacing=8,
            expand=True,
        )

        self._add_game_text("Loading experience...")
        self._page.run_task(self._deferred_init)
        return root

    async def _deferred_init(self) -> None:
        await asyncio.sleep(0.1)
        await self._initialize()

    async def _initialize(self) -> None:
        """Load and start (or resume) the current experience."""
        if_engine = self._state.if_engine_connector
        if if_engine:
            try:
                await if_engine.initialize()
            except Exception as e:
                log.warning("_initialize: Engine initialization check failed: %s", e)

        mgr = self._state.zforge_manager
        exp = self._current_experience
        log.debug("_initialize: STARTING for experience=%s", exp)

        if if_engine is None or mgr is None or exp is None:
            log.debug("_initialize: ABORT - missing context")
            self._add_game_text("No experience selected.")
            return

        compiled_data = mgr.experience_manager.load_experience(exp.zworld_id, exp.name)
        if compiled_data is None:
            log.debug("_initialize: ABORT - no file found for %s/%s", exp.zworld_id, exp.name)
            self._add_game_text("Could not load experience data.")
            return

        try:
            if self._resume and mgr.experience_manager.has_saved_progress(exp.zworld_id, exp.name):
                saved = mgr.experience_manager.load_progress(exp.zworld_id, exp.name)
                await if_engine.start_experience(compiled_data)
                if saved is not None:
                    result = await if_engine.restore_state(saved)
                    self._add_game_text(result.text)
                    self._show_choices(result.choices)
            else:
                text = await if_engine.start_experience(compiled_data)
                state_choices = await if_engine.get_current_choices() if hasattr(if_engine, "get_current_choices") else []
                self._add_game_text(text)
                self._show_choices(state_choices or None)
        except Exception as exc:
            log.exception("Experience initialization failed")
            self._add_game_text(f"Error starting experience: {exc}")
        finally:
            log.debug("_initialize: FINISHED for experience=%s", exp)

    def _add_game_text(self, text: str) -> None:
        """Append game output text to the transcript."""
        self._transcript.value = (self._transcript.value or "") + text.rstrip("\n") + "\n"
        self._page.update()

    def _add_player_text(self, text: str) -> None:
        """Append player input text to the transcript (prefixed with '>>')."""
        self._transcript.value = (self._transcript.value or "") + f">> {text}\n"
        self._page.update()

    def _show_choices(self, choices: list[str] | None) -> None:
        """Display choice buttons."""
        self._choices_box.controls.clear()
        if not choices:
            self._page.update()
            return
        for i, choice_text in enumerate(choices):
            btn = ft.ElevatedButton(
                f"{i + 1}. {choice_text}",
                on_click=lambda e, idx=i: self._page.run_task(self._select_choice, idx),
            )
            self._choices_box.controls.append(btn)
        self._page.update()

    async def _select_choice(self, index: int) -> None:
        """Handle a choice selection."""
        if_engine = self._state.if_engine_connector
        if if_engine is None:
            return

        choices = await if_engine.get_current_choices() if hasattr(if_engine, 'get_current_choices') else []
        if index < len(choices):
            self._add_player_text(choices[index])

        result = await if_engine.take_action(str(index))
        self._add_game_text(result.text)
        self._show_choices(result.choices)

        if result.is_complete:
            self._add_game_text("\n— Experience Complete —")
            self._choices_box.controls.clear()
            self._page.update()

    def _on_submit_input(self) -> None:
        text = self._text_input.value.strip()
        if text:
            self._text_input.value = ""
            self._page.update()
            try:
                index = int(text) - 1
                self._page.run_task(self._select_choice, index)
            except ValueError:
                pass

    def _on_save(self, e: ft.Event[ft.Button]) -> None:
        self._page.run_task(self._do_save)

    async def _do_save(self) -> None:
        if_engine = self._state.if_engine_connector
        mgr = self._state.zforge_manager
        exp = self._current_experience
        if if_engine is None or mgr is None or exp is None:
            return
        state_bytes = await if_engine.save_state()
        mgr.experience_manager.save_progress(exp.zworld_id, exp.name, state_bytes)
        self._add_game_text("Progress saved.")

    def _on_restore(self, e: ft.Event[ft.Button]) -> None:
        self._page.run_task(self._do_restore)

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

    def _on_home(self, e: ft.Event[ft.Button]) -> None:
        from zforge.app import navigate
        from zforge.ui.screens.home_screen import HomeScreen

        screen = HomeScreen(self._page, self._state)
        navigate(self._page, screen.build())
        screen.refresh()
