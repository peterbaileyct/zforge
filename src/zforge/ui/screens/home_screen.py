"""Home Screen.

Displays world list and conditional action buttons.
Implements: src/zforge/ui/screens/home_screen.py per docs/User Experience.md.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

if TYPE_CHECKING:
    from zforge.app_state import AppState
    from zforge.models.results import Experience


class HomeScreen:
    """Home screen showing available worlds and action buttons."""

    def __init__(self, app: toga.App, app_state: AppState) -> None:
        self._app = app
        self._state = app_state
        self._box = toga.Box(style=Pack(direction=COLUMN, padding=10))
        self._world_list = toga.Table(
            headings=["World Name"],
            style=Pack(flex=1),
            on_select=self._on_world_selected,
        )
        self._selected_world_slug: str | None = None
        self._exp_label = toga.Label(
            "Experiences",
            style=Pack(padding_top=8, padding_bottom=2),
        )
        self._experience_list = toga.Table(
            headings=["Experience"],
            style=Pack(flex=1),
            on_select=self._on_experience_selected,
        )
        self._selected_experience: Experience | None = None
        self._experiences: list = []
        self._build_ui()

    def _build_ui(self) -> None:
        title = toga.Label(
            "Z-Forge",
            style=Pack(padding_bottom=10, font_size=20, font_weight="bold"),
        )
        self._box.add(title)
        self._box.add(self._world_list)

        self._box.add(self._exp_label)
        self._box.add(self._experience_list)

        button_row = toga.Box(style=Pack(direction=ROW, padding_top=10))
        self._btn_create_world = toga.Button(
            "Create World",
            on_press=self._on_create_world,
            style=Pack(padding=5),
        )
        button_row.add(self._btn_create_world)

        self._btn_details = toga.Button(
            "Details",
            on_press=self._on_details,
            style=Pack(padding=5),
        )
        button_row.add(self._btn_details)

        self._btn_create_experience = toga.Button(
            "Create Experience",
            on_press=self._on_create_experience,
            style=Pack(padding=5),
        )
        button_row.add(self._btn_create_experience)

        self._btn_start_experience = toga.Button(
            "Start Experience",
            on_press=self._on_start_experience,
            style=Pack(padding=5),
        )
        button_row.add(self._btn_start_experience)

        self._btn_resume = toga.Button(
            "Resume Experience",
            on_press=self._on_resume_experience,
            style=Pack(padding=5),
        )
        button_row.add(self._btn_resume)

        self._btn_llm_config = toga.Button(
            "LLM Configuration",
            on_press=self._on_llm_config,
            style=Pack(padding=5),
        )
        button_row.add(self._btn_llm_config)

        self._box.add(button_row)

    def refresh(self) -> None:
        """Reload world list and update button visibility."""
        mgr = self._state.zforge_manager
        if mgr is None:
            return

        # Reset selection if it's no longer valid
        self._selected_world_slug = None

        worlds = mgr.zworld_manager.list_all()
        self._world_list.data.clear()
        self._worlds = worlds
        for w in worlds:
            self._world_list.data.append(w.title)

        has_worlds = len(worlds) > 0
        self._btn_create_experience.enabled = has_worlds
        self._btn_details.enabled = False

        self._refresh_experience_list()

        experiences = mgr.experience_manager.list_all()
        self._btn_start_experience.enabled = len(experiences) > 0

        saved = mgr.experience_manager.list_saved_experiences()
        self._btn_resume.enabled = len(saved) > 0

    def _refresh_experience_list(self) -> None:
        """Reload experience table based on selected world (or all worlds)."""
        self._experience_list.data.clear()
        self._selected_experience = None
        mgr = self._state.zforge_manager
        if mgr is None:
            return

        if self._selected_world_slug:
            self._exp_label.style.visibility = "visible"
            self._experience_list.style.visibility = "visible"
            experiences = mgr.experience_manager.list_for_world(self._selected_world_slug)
        else:
            self._exp_label.style.visibility = "hidden"
            self._experience_list.style.visibility = "hidden"
            experiences = []

        self._experiences: list = experiences
        for exp in experiences:
            self._experience_list.data.append(exp.name)

    def _on_world_selected(self, widget, **kwargs) -> None:
        row = self._world_list.selection
        if row and self._state.zforge_manager:
            idx = self._world_list.data.index(row)
            if 0 <= idx < len(self._worlds):
                self._selected_world_slug = self._worlds[idx].slug
                self._btn_details.enabled = True
                self._refresh_experience_list()

    def _on_experience_selected(self, widget, **kwargs) -> None:
        row = self._experience_list.selection
        if row and hasattr(self, "_experiences"):
            idx = self._experience_list.data.index(row)
            if 0 <= idx < len(self._experiences):
                self._selected_experience = self._experiences[idx]

    def _on_create_world(self, widget) -> None:
        from zforge.ui.screens.create_world_screen import CreateWorldScreen
        screen = CreateWorldScreen(self._app, self._state, on_done=self.refresh)
        self._app.main_window.content = screen.box

    def _on_details(self, widget) -> None:
        if self._selected_world_slug:
            from zforge.ui.screens.world_details_screen import WorldDetailsScreen
            screen = WorldDetailsScreen(
                self._app, self._state, self._selected_world_slug, on_done=self.refresh
            )
            self._app.main_window.content = screen.box

    def _on_create_experience(self, widget) -> None:
        if self._selected_world_slug and self._state.zforge_manager:
            zworld = self._state.zforge_manager.zworld_manager.read(
                self._selected_world_slug
            )
            if zworld:
                from zforge.ui.screens.generate_experience_screen import (
                    GenerateExperienceScreen,
                )
                screen = GenerateExperienceScreen(
                    self._app, self._state, zworld, on_done=self.refresh
                )
                self._app.main_window.content = screen.box

    def _on_start_experience(self, widget) -> None:
        exp = self._selected_experience
        if exp is None and hasattr(self, "_experiences") and len(self._experiences) == 1:
            exp = self._experiences[0]
        if exp is not None:
            from zforge.ui.screens.gameplay_screen import GameplayScreen
            screen = GameplayScreen(self._app, self._state, experience=exp)
            self._app.main_window.content = screen.box

    def _on_resume_experience(self, widget) -> None:
        exp = self._selected_experience
        if exp is None and hasattr(self, "_experiences") and len(self._experiences) == 1:
            exp = self._experiences[0]
        if exp is not None:
            from zforge.ui.screens.gameplay_screen import GameplayScreen
            screen = GameplayScreen(self._app, self._state, experience=exp, resume=True)
            self._app.main_window.content = screen.box

    def _on_llm_config(self, widget) -> None:
        from zforge.ui.screens.llm_config_screen import LlmConfigScreen

        screen = LlmConfigScreen(self._app, self._state, on_done=self.refresh)
        self._app.main_window.content = screen.box

    @property
    def box(self) -> toga.Box:
        return self._box
