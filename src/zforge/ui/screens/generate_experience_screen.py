"""Generate Experience Screen.

Displays world name, optional prompt input, progress during generation.
Implements: src/zforge/ui/screens/generate_experience_screen.py per
docs/User Experience.md.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

import flet as ft

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from zforge.app_state import AppState
    from zforge.models.zworld import ZWorld


class GenerateExperienceScreen:
    """Screen for generating an experience from a selected ZWorld."""

    def __init__(
        self,
        page: ft.Page,
        app_state: AppState,
        zworld: ZWorld,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        self._page = page
        self._state = app_state
        self._zworld = zworld
        self._on_done = on_done
        self._last_experience = None

    def build(self) -> ft.Control:
        self._progress_label = ft.Text("")
        self._rationale_label = ft.Text("", italic=True)
        self._action_log = ft.TextField(
            multiline=True,
            read_only=True,
            expand=True,
            min_lines=8,
        )

        self._prompt_input = ft.TextField(
            multiline=True,
            expand=True,
            hint_text="Describe the kind of experience you want...",
        )

        self._generate_btn = ft.ElevatedButton(
            "Generate",
            on_click=self._on_generate,
        )

        gen_controls: list[ft.Control] = [
            ft.Text("Generate Experience", size=16, weight=ft.FontWeight.BOLD),
            ft.Text(f"World: {self._zworld.title}"),
            ft.Text("Player Prompt (optional):"),
            self._prompt_input,
            self._generate_btn,
            ft.ElevatedButton("Back", on_click=self._on_back),
            self._progress_label,
            self._rationale_label,
            self._action_log,
        ]
        self._root = ft.Column(
            gen_controls,
            spacing=10,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        return self._root

    def _on_generate(self, e: ft.Event[ft.Button]) -> None:
        self._generate_btn.disabled = True
        self._progress_label.value = "Starting experience generation..."
        self._page.update()
        prompt = self._prompt_input.value.strip() or None
        log.info("_on_generate: scheduling generation for world=%r prompt=%r", self._zworld.slug, prompt)
        self._page.run_task(self._run_generation, prompt)

    async def _run_generation(self, player_prompt: str | None) -> None:
        log.info("_run_generation: ENTERED world=%r prompt=%r", self._zworld.slug, player_prompt)
        mgr = self._state.zforge_manager
        if mgr is None:
            self._progress_label.value = "Error: Not initialized."
            self._page.update()
            return

        def on_update(msg: str) -> None:
            self._progress_label.value = msg
            self._page.update()

        def on_rationale(msg: str, entry: dict[str, Any]) -> None:
            self._rationale_label.value = msg
            self._action_log.value += f"\n- {msg}"
            self._page.update()

        try:
            log.info("_run_generation: calling start_experience_generation")
            experience = await mgr.start_experience_generation(
                world_slug=self._zworld.slug,
                player_prompt=player_prompt,
                on_progress=on_update,
                on_rationale=on_rationale,
            )
            log.info("_run_generation: start_experience_generation returned %r", type(experience))

            if experience is not None:
                self._last_experience = experience
                self._progress_label.value = "Experience created! Play now?"
                play_btn = ft.ElevatedButton(
                    "Play Now",
                    on_click=self._on_play,
                )
                self._root.controls.append(play_btn)
                self._page.update()
            else:
                self._progress_label.value = "Experience generation failed."
                self._generate_btn.disabled = False
                self._page.update()
        except Exception as exc:
            log.exception("Experience generation task failed")
            self._progress_label.value = f"Failed: {exc}"
            self._generate_btn.disabled = False
            self._page.update()

    def _on_play(self, e: ft.Event[ft.Button]) -> None:
        from zforge.app import navigate
        from zforge.ui.screens.gameplay_screen import GameplayScreen

        screen = GameplayScreen(self._page, self._state, experience=self._last_experience)
        navigate(self._page, screen.build())

    def _on_back(self, e: ft.Event[ft.Button]) -> None:
        if self._on_done:
            self._on_done()
