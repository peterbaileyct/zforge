"""World Details Screen.

Displays world title, summary, and a question/answer interface.
Shows an embedding mismatch warning when the configured model differs
from what was used to encode the bundle.

Implements: src/zforge/ui/screens/world_details_screen.py per
docs/User Experience.md — World Details Screen section.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import flet as ft

if TYPE_CHECKING:
    from zforge.app_state import AppState


class WorldDetailsScreen:
    """Read-only world details with a Q&A interface backed by agentic RAG."""

    def __init__(
        self,
        page: ft.Page,
        app_state: AppState,
        slug: str,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        self._page = page
        self._state = app_state
        self._slug = slug
        self._on_done = on_done

    def build(self) -> ft.Control:
        mgr = self._state.zforge_manager
        if mgr is None:
            return ft.Column([ft.Text("Error: not initialized.")])

        zworld = mgr.zworld_manager.read(self._slug)
        if zworld is None:
            not_found: list[ft.Control] = [
                ft.Text(f"World '{self._slug}' not found."),
                ft.ElevatedButton("Back", on_click=self._on_back),
            ]
            return ft.Column(not_found)

        controls: list[ft.Control] = []

        # Embedding mismatch warning
        if mgr.zworld_manager.check_embedding_mismatch(self._slug):
            controls.append(
                ft.Text(
                    "⚠ This world was encoded with a different embedding model. "
                    "Search quality may be degraded until it is re-encoded.",
                    italic=True,
                    color="#b8860b",
                )
            )

        controls.append(ft.Text(zworld.title, size=20, weight=ft.FontWeight.BOLD))

        controls.append(
            ft.TextField(
                read_only=True,
                multiline=True,
                value=zworld.summary,
                expand=True,
            )
        )

        self._question_input = ft.TextField(
            hint_text="Ask a question about this world\u2026",
            expand=True,
        )
        self._ask_btn = ft.ElevatedButton("Ask", on_click=self._on_ask)
        controls.append(ft.Row([self._question_input, self._ask_btn]))

        self._answer_area = ft.TextField(
            read_only=True,
            multiline=True,
            expand=True,
        )
        controls.append(self._answer_area)
        controls.append(ft.ElevatedButton("Back", on_click=self._on_back))

        return ft.Column(controls, spacing=10, expand=True)

    def _on_ask(self, e: ft.Event[ft.Button]) -> None:
        question = self._question_input.value.strip()
        if not question:
            self._answer_area.value = "Please enter a question."
            self._page.update()
            return

        self._ask_btn.disabled = True
        self._answer_area.value = "\u2026"
        self._page.update()
        self._page.run_task(self._run_ask, question)

    async def _run_ask(self, question: str) -> None:
        mgr = self._state.zforge_manager
        if mgr is None:
            self._answer_area.value = "Error: not initialized."
            self._ask_btn.disabled = False
            self._page.update()
            return

        try:
            answer = await mgr.ask_about_world(self._slug, question)
            self._answer_area.value = answer if answer else "No answer generated."
        except Exception as exc:
            self._answer_area.value = f"Error: {exc}"
        finally:
            self._ask_btn.disabled = False
            self._page.update()

    def _on_back(self, e: ft.Event[ft.Button]) -> None:
        if self._on_done:
            self._on_done()
