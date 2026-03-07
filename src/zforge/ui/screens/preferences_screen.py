"""Preferences Screen.

Sliders for all player preference dimensions plus free-text general preferences.
Implements: src/zforge/ui/screens/preferences_screen.py per
docs/Player Preferences.md and docs/User Experience.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

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
        app: toga.App,
        app_state: AppState,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        self._app = app
        self._state = app_state
        self._on_done = on_done
        self._sliders: dict[str, toga.Slider] = {}
        self._slider_labels: dict[str, toga.Label] = {}
        self._box = toga.Box(style=Pack(direction=COLUMN, padding=10))
        self._build_ui()

    def _build_ui(self) -> None:
        title = toga.Label(
            "Player Preferences",
            style=Pack(padding_bottom=10, font_size=16, font_weight="bold"),
        )
        self._box.add(title)

        config = self._state.config_service
        prefs = config.load().preferences if config else None

        for field_name, label_text, hint in _SCALES:
            row = toga.Box(style=Pack(direction=COLUMN, padding_bottom=10))
            label = toga.Label(f"{label_text} ({hint}):", style=Pack())
            row.add(label)

            current_val = getattr(prefs, field_name, 5) if prefs else 5
            value_label = toga.Label(str(current_val), style=Pack(padding_left=5))
            self._slider_labels[field_name] = value_label

            slider = toga.Slider(
                min=1,
                max=10,
                value=current_val,
                on_change=lambda widget, fn=field_name: self._on_slider_change(fn, widget),
                style=Pack(flex=1),
            )
            self._sliders[field_name] = slider

            slider_row = toga.Box(style=Pack(direction=ROW))
            slider_row.add(slider)
            slider_row.add(value_label)
            row.add(slider_row)
            self._box.add(row)

        # General preferences free text
        gen_label = toga.Label("General Preferences:", style=Pack(padding_top=5))
        self._box.add(gen_label)
        self._general_input = toga.MultilineTextInput(
            style=Pack(flex=1, padding_bottom=10),
            value=prefs.general_preferences if prefs else "",
        )
        self._box.add(self._general_input)

        save_btn = toga.Button(
            "Save Preferences",
            on_press=self._on_save,
            style=Pack(padding_top=5),
        )
        self._box.add(save_btn)

    def _on_slider_change(self, field_name: str, widget) -> None:
        self._slider_labels[field_name].text = str(int(widget.value))

    def _on_save(self, widget) -> None:
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

    @property
    def box(self) -> toga.Box:
        return self._box
