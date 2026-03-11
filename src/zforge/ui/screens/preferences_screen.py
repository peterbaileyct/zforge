"""Preferences Screen.

Sliders for all player preference dimensions plus free-text general preferences.
Implements: src/zforge/ui/screens/preferences_screen.py per
docs/Player Preferences.md and docs/User Experience.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import flet as ft

if TYPE_CHECKING:
    from zforge.app_state import AppState


_SCALES = [
    ("character_to_plot", "Character ↔ Plot", "1=Character, 10=Plot"),
    ("narrative_to_dialog", "Narrative ↔ Dialog", "1=Narrative, 10=Dialog"),
    ("puzzle_complexity", "Puzzle Complexity", "1=Minimal, 10=Challenging"),
    ("levity", "Levity", "1=Somber, 10=Comedic"),
    (
        "logical_vs_mood",
        "Logical vs. Mood",
        "1=Mood priority, 10=Logic priority",
    ),
]


class PreferencesScreen:
    """Screen for editing player preferences."""

    def __init__(
        self,
        page: ft.Page,
        app_state: AppState,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        self._page = page
        self._state = app_state
        self._on_done = on_done
        self._sliders: dict[str, ft.Slider] = {}
        self._slider_labels: dict[str, ft.Text] = {}

    def build(self) -> ft.Control:
        config = self._state.config_service
        prefs = config.load().preferences if config else None

        scale_controls: list[ft.Control] = []
        for field_name, label_text, hint in _SCALES:
            current_val = getattr(prefs, field_name, 5) if prefs else 5
            value_label = ft.Text(str(current_val))
            self._slider_labels[field_name] = value_label

            slider = ft.Slider(
                min=1,
                max=10,
                value=current_val,
                divisions=9,
                on_change=lambda e, fn=field_name: self._on_slider_change(fn, e),
                expand=True,
            )
            self._sliders[field_name] = slider

            scale_controls.append(
                ft.Column(
                    [
                        ft.Text(f"{label_text} ({hint}):"),
                        ft.Row([slider, value_label]),
                    ],
                    spacing=4,
                )
            )

        self._general_input = ft.TextField(
            multiline=True,
            expand=True,
            value=prefs.general_preferences if prefs else "",
        )

        return ft.Column(
            [
                ft.Text("Player Preferences", size=16, weight=ft.FontWeight.BOLD),
                *scale_controls,
                ft.Text("General Preferences:"),
                self._general_input,
                ft.ElevatedButton("Save Preferences", on_click=self._on_save),
            ],
            spacing=10,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )

    def _on_slider_change(self, field_name: str, e: ft.ControlEvent) -> None:
        self._slider_labels[field_name].value = str(int(e.control.value))
        self._page.update()

    def _on_save(self, e: ft.ControlEvent) -> None:
        config_svc = self._state.config_service
        if config_svc is None:
            return

        config = config_svc.load()
        for field_name, _, _ in _SCALES:
            setattr(
                config.preferences,
                field_name,
                int(self._sliders[field_name].value),
            )
        config.preferences.general_preferences = self._general_input.value
        config_svc.save(config)

        if self._on_done:
            self._on_done()
