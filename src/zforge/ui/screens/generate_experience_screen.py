"""Generate Experience Screen.

Displays world name, optional prompt input, progress during generation.
Implements: src/zforge/ui/screens/generate_experience_screen.py per
docs/User Experience.md.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Callable

import toga

log = logging.getLogger(__name__)
from toga.style import Pack
from toga.style.pack import COLUMN
import logging

if TYPE_CHECKING:
    from zforge.app_state import AppState
    from zforge.models.zworld import ZWorld


class GenerateExperienceScreen:
    """Screen for generating an experience from a selected ZWorld."""

    def __init__(
        self,
        app: toga.App,
        app_state: AppState,
        zworld: ZWorld,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        self._app = app
        self._state = app_state
        self._zworld = zworld
        self._on_done = on_done
        self._last_experience = None
        self._box = toga.Box(style=Pack(direction=COLUMN, padding=10))
        self._progress_label = toga.Label("", style=Pack(padding_top=10, flex=1))
        self._rationale_label = toga.Label("", style=Pack(padding_top=5, font_style="italic", flex=1))
        self._action_log = toga.MultilineTextInput(
            readonly=True,
            style=Pack(flex=1, padding_top=5, height=180),
        )
        self._build_ui()

    def _build_ui(self) -> None:
        title = toga.Label(
            "Generate Experience",
            style=Pack(padding_bottom=10, font_size=16, font_weight="bold"),
        )
        self._box.add(title)

        world_label = toga.Label(
            f"World: {self._zworld.title}",
            style=Pack(padding_bottom=10),
        )
        self._box.add(world_label)

        prompt_label = toga.Label(
            "Player Prompt (optional):",
            style=Pack(padding_bottom=5),
        )
        self._box.add(prompt_label)

        self._prompt_input = toga.MultilineTextInput(
            style=Pack(flex=1, padding_bottom=10),
            placeholder="Describe the kind of experience you want...",
        )
        self._box.add(self._prompt_input)

        self._generate_btn = toga.Button(
            "Generate",
            on_press=self._on_generate,
            style=Pack(padding_bottom=5),
        )
        self._box.add(self._generate_btn)

        back_btn = toga.Button(
            "Back",
            on_press=self._on_back,
            style=Pack(padding_bottom=5),
        )
        self._box.add(back_btn)
        self._box.add(self._progress_label)
        self._box.add(self._rationale_label)
        self._box.add(self._action_log)

    def _on_generate(self, widget) -> None:
        self._generate_btn.enabled = False
        self._progress_label.text = "Starting experience generation..."
        prompt = self._prompt_input.value.strip() or None
        # Schedule background generation and attach a done callback so
        # exceptions don't vanish silently — they will be logged to the
        # application console for easier debugging.
        task = asyncio.ensure_future(self._run_generation(prompt))

        log = logging.getLogger(__name__)

        def _on_done(t):
            try:
                _ = t.result()
            except Exception:
                log.exception("Experience generation task failed")

        task.add_done_callback(_on_done)
        # Also print immediately so the console definitely shows activity
        print("_on_generate: scheduled background generation task for world=", self._zworld.slug, "prompt=", prompt)

    async def _run_generation(self, player_prompt: str | None) -> None:
        print("_run_generation: ENTERED world=", self._zworld.slug, "prompt=", player_prompt)
        log.info("_run_generation: ENTERED  world=%r prompt=%r", self._zworld.slug, player_prompt)
        mgr = self._state.zforge_manager
        if mgr is None:
            self._progress_label.text = "Error: Not initialized."
            return

        def on_update(msg: str) -> None:
            self._progress_label.text = msg

        try:
            log.info("_run_generation: calling start_experience_generation")
            experience = await mgr.start_experience_generation(
                world_slug=self._zworld.slug,
                player_prompt=player_prompt,
                on_progress=on_update,
            )
            log.info("_run_generation: start_experience_generation returned %r", type(experience))

            if experience is not None:
                self._last_experience = experience
                self._progress_label.text = "Experience created! Play now?"
                play_btn = toga.Button(
                    "Play Now",
                    on_press=self._on_play,
                    style=Pack(padding_top=5),
                )
                self._box.add(play_btn)
            else:
                self._progress_label.text = "Experience generation failed."
                self._generate_btn.enabled = True
        except Exception as exc:
            self._progress_label.text = f"Failed: {exc}"
            self._generate_btn.enabled = True

    def _on_play(self, widget) -> None:
        from zforge.ui.screens.gameplay_screen import GameplayScreen
        screen = GameplayScreen(self._app, self._state, experience=self._last_experience)
        self._app.main_window.content = screen.box

    def _on_back(self, widget) -> None:
        if self._on_done:
            self._on_done()

    @property
    def box(self) -> toga.Box:
        return self._box
