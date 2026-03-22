"""Create Experience Screen.

Displays prompt input, world selection, player preference overrides, and
generation progress.

Implements: src/zforge/ui/screens/generate_experience_screen.py per
docs/User Experience.md § Create Experience Screen.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, Any, Callable

import flet as ft

from zforge.models.zforge_config import PlayerPreferences

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from zforge.app_state import AppState
    from zforge.models.results import Experience


# Scale field definitions: (attr_name, label, min, max, step)
_SCALE_FIELDS: list[tuple[str, str, int, int, int]] = [
    ("character_to_plot", "Character ↔ Plot", 1, 10, 1),
    ("narrative_to_dialog", "Narrative ↔ Dialog", 1, 10, 1),
    ("puzzle_complexity", "Puzzle Complexity", 1, 10, 1),
    ("levity", "Levity", 1, 10, 1),
    ("logical_vs_mood", "Logical vs. Mood", 1, 10, 1),
    ("complexity", "Knot Count (Complexity)", 3, 20, 1),
]


class GenerateExperienceScreen:
    """Screen for creating and generating an experience."""

    def __init__(
        self,
        page: ft.Page,
        app_state: AppState,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        self._page = page
        self._state = app_state
        self._on_done = on_done
        self._last_experience: Experience | None = None
        cs = app_state.config_service
        stored = cs.load() if cs is not None else None
        self._stored_prefs: PlayerPreferences = (
            dataclasses.replace(stored.preferences) if stored is not None
            else PlayerPreferences()
        )
        self._override_values: dict[str, int | str] = {}
        self._world_checkboxes: list[tuple[str, ft.Checkbox]] = []
        self._slider_controls: dict[str, ft.Slider] = {}

    def build(self) -> ft.Control:
        prefs = self._stored_prefs

        # --- Prompt ---
        self._prompt_input = ft.TextField(
            multiline=True,
            expand=True,
            min_lines=3,
            hint_text="Describe the experience you want…",
            on_change=self._on_prompt_change,
        )

        # --- Generate button (disabled until prompt non-empty) ---
        self._generate_btn = ft.ElevatedButton(
            "Generate",
            on_click=self._on_generate,
            disabled=True,
        )

        # --- World selection ---
        world_list_controls: list[ft.Control] = []
        mgr = self._state.zforge_manager
        if mgr is not None:
            worlds = mgr.zworld_manager.list_all()
            for w in worlds:
                cb = ft.Checkbox(label=w.title, value=False, data=w.slug)
                self._world_checkboxes.append((w.slug, cb))
                world_list_controls.append(cb)

        if not world_list_controls:
            world_list_controls.append(
                ft.Text("No worlds available.", italic=True)
            )

        world_section = ft.Column(
            [
                ft.Text(
                    "Create Your Universe",
                    size=14,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Column(
                    world_list_controls,
                    scroll=ft.ScrollMode.AUTO,
                    height=150,
                ),
            ],
            spacing=6,
        )

        # --- Player Preferences Override ---
        pref_controls: list[ft.Control] = []

        for attr, label, lo, hi, step in _SCALE_FIELDS:
            val = float(getattr(prefs, attr))
            slider = ft.Slider(
                min=lo,
                max=hi,
                divisions=(hi - lo) // step,
                value=val,
                label=f"{{value}}",
                on_change=self._make_slider_change(attr),
                expand=True,
            )
            self._slider_controls[attr] = slider
            pref_controls.append(
                ft.Row(
                    [ft.Text(label, width=180), slider],
                    spacing=8,
                )
            )

        # Length — numeric Slider (1000–15000)
        length_slider = ft.Slider(
            min=1000,
            max=15000,
            divisions=14,
            value=float(prefs.length),
            label="{value} words",
            on_change=self._make_slider_change("length"),
            expand=True,
        )
        self._slider_controls["length"] = length_slider
        pref_controls.append(
            ft.Row(
                [ft.Text("Target Length (words)", width=180), length_slider],
                spacing=8,
            )
        )

        # General preferences — TextField
        self._general_pref_input = ft.TextField(
            value=prefs.general_preferences,
            hint_text="Describe any other preferences…",
            multiline=True,
            min_lines=2,
            expand=True,
            on_change=self._on_general_pref_change,
        )
        pref_controls.append(
            ft.Row(
                [
                    ft.Text("General Preferences", width=180),
                    self._general_pref_input,
                ],
                spacing=8,
            )
        )

        self._prefs_badge = ft.Text("using defaults", italic=True, size=12)
        self._prefs_tile = ft.ExpansionTile(
            title=ft.Text("Player Preferences Override"),
            subtitle=self._prefs_badge,
            expanded=False,
            controls=[ft.Column(pref_controls, spacing=8)],
        )

        # --- Progress area ---
        self._progress_label = ft.Text("")
        self._rationale_label = ft.Text("", italic=True)
        self._action_log = ft.TextField(
            multiline=True,
            read_only=True,
            expand=True,
            min_lines=8,
        )

        back_btn = ft.ElevatedButton("Back", on_click=self._on_back)

        self._root = ft.Column(
            [
                ft.Text(
                    "Create Experience",
                    size=16,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text("Prompt (required):"),
                self._prompt_input,
                world_section,
                self._prefs_tile,
                ft.Row(
                    controls=[self._generate_btn, back_btn],
                ),
                self._progress_label,
                self._rationale_label,
                self._action_log,
            ],
            spacing=10,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        return self._root

    # --- Event handlers ---

    def _on_prompt_change(self, e: ft.Event[ft.TextField]) -> None:
        has_text = bool(
            self._prompt_input.value and self._prompt_input.value.strip()
        )
        self._generate_btn.disabled = not has_text
        self._page.update()

    def _make_slider_change(
        self, attr: str
    ) -> Callable[[ft.Event[ft.Slider]], None]:
        def handler(e: ft.Event[ft.Slider]) -> None:
            slider = self._slider_controls[attr]
            self._override_values[attr] = int(slider.value or 0)
            self._update_prefs_badge()

        return handler

    def _on_general_pref_change(self, e: ft.Event[ft.TextField]) -> None:
        self._override_values["general_preferences"] = (
            self._general_pref_input.value or ""
        )
        self._update_prefs_badge()

    def _update_prefs_badge(self) -> None:
        prefs = self._stored_prefs
        count = 0
        for key, val in self._override_values.items():
            stored: int | str = getattr(prefs, key)
            if val != stored:
                count += 1
        self._prefs_badge.value = (
            f"{count} field{'s' if count != 1 else ''} overridden"
            if count > 0
            else "using defaults"
        )
        self._page.update()

    def _get_selected_world_slugs(self) -> list[str]:
        return [slug for slug, cb in self._world_checkboxes if cb.value]

    def _get_merged_preferences(self) -> PlayerPreferences:
        prefs: PlayerPreferences = dataclasses.replace(self._stored_prefs)
        for key, val in self._override_values.items():
            stored: int | str = getattr(prefs, key)
            if val != stored:
                setattr(prefs, key, val)
        return prefs

    def _on_generate(self, e: ft.Event[ft.Button]) -> None:
        prompt = (self._prompt_input.value or "").strip()
        if not prompt:
            return
        self._generate_btn.disabled = True
        self._progress_label.value = "Starting experience generation..."
        self._page.update()

        world_slugs = self._get_selected_world_slugs()
        merged_prefs = self._get_merged_preferences()
        log.info(
            "_on_generate: prompt=%r worlds=%r prefs_overrides=%d",
            prompt[:80],
            world_slugs,
            len(self._override_values),
        )
        self._page.run_task(
            self._run_generation, prompt, world_slugs, merged_prefs
        )

    async def _run_generation(
        self,
        prompt: str,
        world_slugs: list[str],
        player_preferences: PlayerPreferences,
    ) -> None:
        log.info(
            "_run_generation: ENTERED prompt=%r worlds=%r",
            prompt[:80],
            world_slugs,
        )
        mgr = self._state.zforge_manager
        if mgr is None:
            self._progress_label.value = "Error: Not initialized."
            self._page.update()
            return

        def on_update(msg: str) -> None:
            self._progress_label.value = msg
            self._page.update()

        def on_rationale(msg: str, entry: dict[str, Any]) -> None:
            entry_type = entry.get("type", "rationale")
            if entry_type == "tool_call":
                tool = entry.get("tool", "?")
                role = entry.get("role", entry.get("node", "?"))
                args_raw = entry.get("args")
                args: dict[str, object] = (
                    args_raw if isinstance(args_raw, dict) else {}
                )
                args_preview = ", ".join(
                    f"{k}={str(v)[:50]!r}" for k, v in args.items()
                )
                display = f"  > [{role}] {tool}({args_preview})"
                self._action_log.value = (
                    (self._action_log.value or "") + f"\n{display}"
                )
            else:
                self._rationale_label.value = msg
                self._action_log.value = (
                    (self._action_log.value or "") + f"\n- {msg}"
                )
            self._page.update()

        try:
            log.info(
                "_run_generation: calling start_experience_generation"
            )
            experience = await mgr.start_experience_generation(
                player_prompt=prompt,
                world_slugs=world_slugs or None,
                player_preferences=player_preferences,
                on_progress=on_update,
                on_rationale=on_rationale,
            )
            log.info(
                "_run_generation: start_experience_generation returned %r",
                type(experience),
            )

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
                self._progress_label.value = (
                    "Experience generation failed."
                )
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

        screen = GameplayScreen(
            self._page, self._state, experience=self._last_experience
        )
        navigate(self._page, screen.build())

    def _on_back(self, e: ft.Event[ft.Button]) -> None:
        if self._on_done:
            self._on_done()
