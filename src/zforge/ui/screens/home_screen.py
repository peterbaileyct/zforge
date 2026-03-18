"""Home Screen.

Displays world list and conditional action buttons.
Implements: src/zforge/ui/screens/home_screen.py per docs/User Experience.md.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

log = logging.getLogger(__name__)

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
        self._experiences: list[Any] = []
        self._worlds: list[Any] = []

    def build(self) -> ft.Control:
        self._world_list = ft.ListView(
            expand=True,
            spacing=2,
            padding=10,
        )

        self._exp_label = ft.Text("Experiences", weight=ft.FontWeight.BOLD)
        self._experience_list = ft.ListView(
            expand=True,
            spacing=2,
            padding=10,
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
        self._btn_reindex = ft.ElevatedButton(
            "Reindex World", on_click=self._on_reindex_world, disabled=True
        )
        self._btn_llm_config = ft.ElevatedButton(
            "LLM Configuration", on_click=self._on_llm_config
        )

        self._root = ft.Column(
            [
                ft.Text("Z-Forge", size=20, weight=ft.FontWeight.BOLD),
                ft.Text("Worlds", weight=ft.FontWeight.BOLD),
                self._world_list,
                self._exp_label,
                self._experience_list,
                ft.Row(
                    [
                        self._btn_create_world,
                        self._btn_details,
                        self._btn_reindex,
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

        worlds = mgr.zworld_manager.list_all()
        self._worlds = worlds
        self._world_list.controls.clear()
        for w in worlds:
            is_selected = w.slug == self._selected_world_slug
            self._world_list.controls.append(
                ft.ListTile(
                    title=ft.Text(w.title),
                    selected=is_selected,
                    on_click=lambda e, slug=w.slug: self._on_world_selected(slug, e),
                    selected_tile_color=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                )
            )

        has_worlds = len(worlds) > 0
        self._btn_create_experience.disabled = not has_worlds
        self._btn_details.disabled = self._selected_world_slug is None
        self._btn_reindex.disabled = self._selected_world_slug is None

        self._refresh_experience_list()

        experiences = mgr.experience_manager.list_all()
        self._btn_start_experience.disabled = len(experiences) == 0

        saved = mgr.experience_manager.list_saved_experiences()
        self._btn_resume.disabled = len(saved) == 0
        self._page.update()

    def _refresh_experience_list(self) -> None:
        """Reload experience table based on selected world (or all worlds)."""
        self._experience_list.controls.clear()
        self._selected_experience = None
        mgr = self._state.zforge_manager
        if mgr is None:
            return

        if self._selected_world_slug:
            self._exp_label.visible = True
            self._experience_list.visible = True
            experiences = mgr.experience_manager.list_for_world(self._selected_world_slug)
        else:
            self._exp_label.visible = False
            self._experience_list.visible = False
            experiences = []

        self._experiences = experiences
        for exp in experiences:
            is_selected = self._selected_experience and exp.name == self._selected_experience.name
            self._experience_list.controls.append(
                ft.ListTile(
                    title=ft.Text(exp.name),
                    selected=bool(is_selected),
                    on_click=lambda e, ex=exp: self._on_experience_selected(ex, e),
                    selected_tile_color=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                )
            )

    def _on_world_selected(self, slug: str, e: ft.Event[ft.ListTile]) -> None:
        self._selected_world_slug = slug
        self._btn_details.disabled = False
        self._btn_reindex.disabled = False
        
        # Refresh visuals
        self.refresh()

    def _on_experience_selected(self, exp: "Experience", e: ft.Event[ft.ListTile]) -> None:
        self._selected_experience = exp
        self.refresh()

    def _on_create_world(self, e: ft.Event[ft.Button]) -> None:
        from zforge.app import navigate
        from zforge.ui.screens.create_world_screen import CreateWorldScreen

        screen = CreateWorldScreen(self._page, self._state, on_done=self._go_home)
        navigate(self._page, screen.build())

    def _on_details(self, e: ft.Event[ft.Button]) -> None:
        if self._selected_world_slug:
            from zforge.app import navigate
            from zforge.ui.screens.world_details_screen import WorldDetailsScreen

            screen = WorldDetailsScreen(
                self._page, self._state, self._selected_world_slug, on_done=self._go_home
            )
            navigate(self._page, screen.build())

    def _on_create_experience(self, e: ft.Event[ft.Button]) -> None:
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

    def _on_start_experience(self, e: ft.Event[ft.Button]) -> None:
        exp = self._selected_experience
        if exp is None and len(self._experiences) == 1:
            exp = self._experiences[0]
        if exp is not None:
            from zforge.app import navigate
            from zforge.ui.screens.gameplay_screen import GameplayScreen

            screen = GameplayScreen(self._page, self._state, experience=exp)
            navigate(self._page, screen.build())

    def _on_resume_experience(self, e: ft.Event[ft.Button]) -> None:
        exp = self._selected_experience
        if exp is None and len(self._experiences) == 1:
            exp = self._experiences[0]
        if exp is not None:
            from zforge.app import navigate
            from zforge.ui.screens.gameplay_screen import GameplayScreen

            screen = GameplayScreen(self._page, self._state, experience=exp, resume=True)
            navigate(self._page, screen.build())

    def _on_reindex_world(self, e: ft.Event[ft.Button]) -> None:
        if self._selected_world_slug:
            self._page.run_task(self._run_reindex, self._selected_world_slug)

    async def _run_reindex(self, slug: str) -> None:
        try:
            mgr = self._state.zforge_manager
            if mgr is None:
                log.error("_run_reindex: mgr is None")
                return

            progress_label = ft.Text(f"Reindexing '{slug}'...")
            rationale_output = ft.TextField(
                label="Rationale / Action Log",
                multiline=True,
                read_only=True,
                text_size=12,
                min_lines=3,
                max_lines=10,
            )

            dlg = ft.AlertDialog(
                title=ft.Text("Reindex World"),
                content=ft.Container(
                    content=ft.Column(
                        [
                            ft.ProgressRing(),
                            progress_label,
                            rationale_output,
                        ],
                        tight=True,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    height=300,
                    width=400,
                ),
                modal=True,
            )
            
            self._page.show_dialog(dlg)

            def on_update(msg: str) -> None:
                progress_label.value = msg
                self._page.update()

            def on_rationale(rationale: str, entry: dict[str, Any]) -> None:
                # We ensure it hits the debug console via log.info in ZForgeManager.
                # Mirror to UI here.
                current_text = rationale_output.value or ""
                if current_text:
                    current_text += "\n"
                rationale_output.value = current_text + rationale
                self._page.update()

            try:
                result = await mgr.reindex_world(
                    slug, on_progress=on_update, on_rationale=on_rationale
                )
                self._page.pop_dialog()

                if result is not None:
                    self._page.show_dialog(
                        ft.SnackBar(ft.Text(f"World '{slug}' reindexed successfully."), open=True)
                    )
                else:
                    self._page.show_dialog(
                        ft.SnackBar(ft.Text(f"Reindex of '{slug}' failed."), open=True)
                    )
            except Exception as exc:
                log.exception("_run_reindex: failed for slug=%r — %s", slug, exc)
                self._page.pop_dialog()
                self._page.show_dialog(
                    ft.SnackBar(ft.Text(f"Reindex failed: {exc}"), open=True)
                )
        except Exception as e:
            log.exception("_run_reindex: unhandled UI setup exception: %s", e)
        finally:
            self._page.update()

    def _on_llm_config(self, e: ft.Event[ft.Button]) -> None:
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
