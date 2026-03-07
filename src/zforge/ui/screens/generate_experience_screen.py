"""Generate Experience Screen.

Displays world name, optional prompt input, progress during generation.
Implements: src/zforge/ui/screens/generate_experience_screen.py per
docs/User Experience.md.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Callable

import toga
from toga.style import Pack
from toga.style.pack import COLUMN

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
            f"World: {self._zworld.name}",
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
        asyncio.ensure_future(self._run_generation(prompt))

    async def _run_generation(self, player_prompt: str | None) -> None:
        mgr = self._state.zforge_manager
        config_svc = self._state.config_service
        if mgr is None or config_svc is None:
            self._progress_label.text = "Error: Not initialized."
            return

        config = config_svc.load()

        def on_update(msg: str) -> None:
            self._progress_label.text = msg

        def on_rationale(rationale: str, entry: dict) -> None:
            self._rationale_label.text = rationale
            ts = entry.get("timestamp", "")[11:]  # HH:MM:SS from ISO string
            from_s = entry.get("from_status", "?")
            to_s = entry.get("to_status", "?")
            action = entry.get("action", "")
            line = f"{ts} | {from_s} → {to_s}\n  {action}\n  {rationale}\n\n"
            self._action_log.value = (self._action_log.value or "") + line

        result = await mgr.start_experience_generation(
            z_world=self._zworld,
            preferences=config.preferences,
            player_prompt=player_prompt,
            on_status_update=on_update,
            on_rationale_update=on_rationale,
        )

        if result.get("status") == "complete":
            compiled = result.get("compiled_output")
            if compiled and self._state.zforge_manager:
                name = player_prompt[:30].replace(" ", "-") if player_prompt else "experience"
                name = "".join(c for c in name if c.isalnum() or c == "-")
                self._last_experience = self._state.zforge_manager.experience_manager.create(
                    zworld_id=self._zworld.id,
                    name=name,
                    compiled_data=compiled,
                )
            self._progress_label.text = "Experience created! Play now?"
            play_btn = toga.Button(
                "Play Now",
                on_press=self._on_play,
                style=Pack(padding_top=5),
            )
            self._box.add(play_btn)
        else:
            reason = result.get("failure_reason", "Unknown error")
            self._progress_label.text = f"Failed: {reason}"
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
