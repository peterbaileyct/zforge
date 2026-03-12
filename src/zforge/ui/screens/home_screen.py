"""Home Screen.

Displays world list and conditional action buttons.
Implements: src/zforge/ui/screens/home_screen.py per docs/User Experience.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import flet as ft

if TYPE_CHECKING:
    from zforge.app_state import AppState
    from zforge.models.results import Experience


class HomeScreen:
    """Home screen showing available worlds and action buttons."""

    def __init__(self, page: ft.Page, app_state: AppState) -> None:
        self._page = page
        self._state = app_state
        self._selected_world_slug: str | None = None
        self._selected_experience: Experience | None = None
        self._experiences: list = []
        self._worlds: list = []

    def build(self) -> ft.Control:
        self._world_table = ft.DataTable(
            columns=[ft.DataColumn(ft.Text("World Name"))],
            rows=[],
            expand=True,
        )

        self._exp_label = ft.Text("Experiences")
        self._experience_table = ft.DataTable(
            columns=[ft.DataColumn(ft.Text("Experience"))],
            rows=[],
            expand=True,
        )

        self._btn_create_world = ft.ElevatedButton(
            "Create World", on_click=self._on_create_world
        )
        self._btn_details = ft.ElevatedButton(
            "Details", on_click=self._on_details, disabled=True
        )
        self._btn_create_experience = ft.ElevatedButton(
            "Create Experience", on_click=self._on_create_experience
        )
        self._btn_start_experience = ft.ElevatedButton(
            "Start Experience", on_click=self._on_start_experience
        )
        self._btn_resume = ft.ElevatedButton(
            "Resume Experience", on_click=self._on_resume_experience
        )
        self._btn_llm_config = ft.ElevatedButton(
            "LLM Configuration", on_click=self._on_llm_config
        )

        self._root = ft.Column(
            [
                ft.Text("Z-Forge", size=20, weight=ft.FontWeight.BOLD),
                self._world_table,
                self._exp_label,
                self._experience_table,
                ft.Row(
                    [
                        self._btn_create_world,
                        self._btn_details,
                        self._btn_create_experience,
                        self._btn_start_experience,
                        self._btn_resume,
                        self._btn_llm_config,
                    ],
                    wrap=True,
                ),
            ],
            spacing=10,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        return self._root

    def refresh(self) -> None:
        """Reload world list and update button visibility."""
        mgr = self._state.zforge_manager
        if mgr is None:
            return

        self._selected_world_slug = None

        worlds = mgr.zworld_manager.list_all()
        self._worlds = worlds
        self._world_table.rows.clear()
        for w in worlds:
            row = ft.DataRow(
                cells=[ft.DataCell(ft.Text(w.title))],
                on_select_change=lambda e, slug=w.slug: self._on_world_selected(slug, e),
            )
            self._world_table.rows.append(row)

        has_worlds = len(worlds) > 0
        self._btn_create_experience.disabled = not has_worlds
        self._btn_details.disabled = True

        self._refresh_experience_list()

        experiences = mgr.experience_manager.list_all()
        self._btn_start_experience.disabled = len(experiences) == 0

        saved = mgr.experience_manager.list_saved_experiences()
        self._btn_resume.disabled = len(saved) == 0
        self._page.update()

    def _refresh_experience_list(self) -> None:
        """Reload experience table based on selected world (or all worlds)."""
        self._experience_table.rows.clear()
        self._selected_experience = None
        mgr = self._state.zforge_manager
        if mgr is None:
            return

        if self._selected_world_slug:
            self._exp_label.visible = True
            self._experience_table.visible = True
            experiences = mgr.experience_manager.list_for_world(self._selected_world_slug)
        else:
            self._exp_label.visible = False
            self._experience_table.visible = False
            experiences = []

        self._experiences = experiences
        for exp in experiences:
            row = ft.DataRow(
                cells=[ft.DataCell(ft.Text(exp.name))],
                on_select_change=lambda e, ex=exp: self._on_experience_selected(ex, e),
            )
            self._experience_table.rows.append(row)

    def _on_world_selected(self, slug: str, e: ft.ControlEvent) -> None:
        self._selected_world_slug = slug
        self._btn_details.disabled = False
        self._refresh_experience_list()
        self._page.update()

    def _on_experience_selected(self, exp: "Experience", e: ft.ControlEvent) -> None:
        self._selected_experience = exp

    def _on_create_world(self, e: ft.ControlEvent) -> None:
        from zforge.app import navigate
        from zforge.ui.screens.create_world_screen import CreateWorldScreen

        screen = CreateWorldScreen(self._page, self._state, on_done=self._go_home)
        navigate(self._page, screen.build())

    def _on_details(self, e: ft.ControlEvent) -> None:
        if self._selected_world_slug:
            from zforge.app import navigate
            from zforge.ui.screens.world_details_screen import WorldDetailsScreen

            screen = WorldDetailsScreen(
                self._page, self._state, self._selected_world_slug, on_done=self._go_home
            )
            navigate(self._page, screen.build())

    def _on_create_experience(self, e: ft.ControlEvent) -> None:
        if self._selected_world_slug and self._state.zforge_manager:
            zworld = self._state.zforge_manager.zworld_manager.read(
                self._selected_world_slug
            )
            if zworld:
                from zforge.app import navigate
                from zforge.ui.screens.generate_experience_screen import (
                    GenerateExperienceScreen,
                )

                screen = GenerateExperienceScreen(
                    self._page, self._state, zworld, on_done=self._go_home
                )
                navigate(self._page, screen.build())

    def _on_start_experience(self, e: ft.ControlEvent) -> None:
        exp = self._selected_experience
        if exp is None and len(self._experiences) == 1:
            exp = self._experiences[0]
        if exp is not None:
            from zforge.app import navigate
            from zforge.ui.screens.gameplay_screen import GameplayScreen

            screen = GameplayScreen(self._page, self._state, experience=exp)
            navigate(self._page, screen.build())

    def _on_resume_experience(self, e: ft.ControlEvent) -> None:
        exp = self._selected_experience
        if exp is None and len(self._experiences) == 1:
            exp = self._experiences[0]
        if exp is not None:
            from zforge.app import navigate
            from zforge.ui.screens.gameplay_screen import GameplayScreen

            screen = GameplayScreen(self._page, self._state, experience=exp, resume=True)
            navigate(self._page, screen.build())

    def _on_llm_config(self, e: ft.ControlEvent) -> None:
        from zforge.app import navigate
        from zforge.ui.screens.llm_config_screen import LlmConfigScreen

        screen = LlmConfigScreen(self._page, self._state, on_done=self._go_home)
        navigate(self._page, screen.build())

    def _go_home(self) -> None:
        """Navigate back to a fresh home screen."""
        from zforge.app import navigate

        screen = HomeScreen(self._page, self._state)
        navigate(self._page, screen.build())
        screen.refresh()
