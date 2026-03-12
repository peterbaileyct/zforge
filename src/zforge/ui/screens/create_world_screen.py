"""Create World Screen.

Text input for world description, progress display during LangGraph run.
Implements: src/zforge/ui/screens/create_world_screen.py per
docs/User Experience.md and docs/World Generation.md.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Callable

import flet as ft

if TYPE_CHECKING:
    from zforge.app_state import AppState


class CreateWorldScreen:
    """Screen for creating a new ZWorld from a text description."""

    def __init__(
        self,
        page: ft.Page,
        app_state: AppState,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        self._page = page
        self._state = app_state
        self._on_done = on_done

    def build(self) -> ft.Control:
        self._progress_label = ft.Text("")

        self._text_input = ft.TextField(
            multiline=True,
            expand=True,
            hint_text="Describe characters, locations, relationships, and events...",
        )

        self._create_btn = ft.ElevatedButton(
            "Create World",
            on_click=self._on_create,
        )

        return ft.Column(
            [
                ft.Text("Create World", size=16, weight=ft.FontWeight.BOLD),
                ft.Text("Enter a description of your fictional world below:"),
                self._text_input,
                self._create_btn,
                ft.ElevatedButton("Back", on_click=self._on_back),
                self._progress_label,
            ],
            spacing=10,
            expand=True,
        )

    def _on_create(self, e: ft.ControlEvent) -> None:
        description = self._text_input.value.strip()
        if not description:
            self._progress_label.value = "Please enter a world description."
            self._page.update()
            return

        self._create_btn.disabled = True
        self._progress_label.value = "Starting world creation..."
        self._page.update()
        self._page.run_task(self._run_creation, description)

    async def _confirm_duplicate(self, conflicting_slug: str) -> str:
        """Show a dialog asking whether to overwrite an existing world.

        Returns ``"overwrite"`` or ``"cancel"``.
        """
        result_event = asyncio.Event()
        result_holder: list[str] = ["cancel"]

        def _on_overwrite(e: ft.ControlEvent) -> None:
            result_holder[0] = "overwrite"
            dlg.open = False
            self._page.update()
            result_event.set()

        def _on_cancel(e: ft.ControlEvent) -> None:
            result_holder[0] = "cancel"
            dlg.open = False
            self._page.update()
            result_event.set()

        dlg = ft.AlertDialog(
            title=ft.Text("Duplicate World"),
            content=ft.Text(
                f"A world with slug '{conflicting_slug}' already exists.\n\n"
                "Would you like to overwrite it?"
            ),
            actions=[
                ft.TextButton("Overwrite", on_click=_on_overwrite),
                ft.TextButton("Cancel", on_click=_on_cancel),
            ],
            open=True,
        )
        self._page.overlay.append(dlg)
        self._page.update()

        await result_event.wait()
        if dlg in self._page.overlay:
            self._page.overlay.remove(dlg)
        return result_holder[0]

    async def _run_creation(self, description: str) -> None:
        mgr = self._state.zforge_manager
        if mgr is None:
            self._progress_label.value = "Error: Manager not initialized."
            self._page.update()
            return

        def on_update(msg: str) -> None:
            self._progress_label.value = msg
            self._page.update()

        try:
            zworld = await mgr.start_world_creation(
                input_text=description,
                on_progress=on_update,
                on_confirm_duplicate=self._confirm_duplicate,
            )

            if zworld is not None:
                self._progress_label.value = "World created successfully!"
                self._page.update()
                if self._on_done:
                    self._on_done()
            else:
                self._progress_label.value = "World creation cancelled or failed."
                self._create_btn.disabled = False
                self._page.update()
        except Exception as exc:
            self._progress_label.value = f"Failed: {exc}"
            self._create_btn.disabled = False
            self._page.update()

    def _on_back(self, e: ft.ControlEvent) -> None:
        if self._on_done:
            self._on_done()
