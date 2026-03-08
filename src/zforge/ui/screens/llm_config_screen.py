"""LLM Configuration Screen.

Model picker + download UI. The user selects a chat model from the
catalogue; pressing Download fetches the chosen chat model and the
default embedding model concurrently, showing per-file progress bars.

Implements: src/zforge/ui/screens/llm_config_screen.py per
docs/User Experience.md and docs/Local LLM Execution.md.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import toga
from platformdirs import user_data_dir
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

from zforge.models.model_catalogue import CATALOGUE, ModelCatalogueEntry
from zforge.services.model_download_service import ModelDownloadService

if TYPE_CHECKING:
    from zforge.app_state import AppState

log = logging.getLogger(__name__)

_MODELS_SUBDIR = "models"


def _format_size(size_bytes: int) -> str:
    """Return a human-readable size string."""
    if size_bytes >= 1_000_000_000:
        return f"~{size_bytes / 1_073_741_824:.1f} GB"
    return f"~{size_bytes / 1_048_576:.0f} MB"


class LlmConfigScreen:
    """Screen for selecting and downloading local GGUF models."""

    def __init__(
        self,
        app: toga.App,
        app_state: AppState,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        self._app = app
        self._state = app_state
        self._on_done = on_done

        self._chat_entries = [e for e in CATALOGUE if e.role == "chat"]
        self._embedding_entry = next(
            e for e in CATALOGUE if e.role == "embedding" and e.is_default
        )

        self._box = toga.Box(style=Pack(direction=COLUMN, padding=10))
        self._size_label: toga.Label | None = None
        self._download_btn: toga.Button | None = None
        self._selection: toga.Selection | None = None
        self._status_label: toga.Label | None = None
        self._chat_bar: toga.ProgressBar | None = None
        self._embed_bar: toga.ProgressBar | None = None
        self._chat_bar_label: toga.Label | None = None
        self._embed_bar_label: toga.Label | None = None
        self._progress_box: toga.Box | None = None

        self._build_ui()

    def _selected_chat_entry(self) -> ModelCatalogueEntry:
        """Return the currently selected chat catalogue entry."""
        if self._selection is None:
            return self._chat_entries[0]
        selected_name = self._selection.value
        for entry in self._chat_entries:
            if entry.display_name == selected_name:
                return entry
        return self._chat_entries[0]

    def _update_size_label(self, widget=None) -> None:
        """Update the download-size label when the selection changes."""
        if self._size_label is None:
            return
        chat = self._selected_chat_entry()
        total = chat.size_bytes_approx + self._embedding_entry.size_bytes_approx
        self._size_label.text = (
            f"Total download: {_format_size(total)} "
            f"(chat {_format_size(chat.size_bytes_approx)} "
            f"+ embedding {_format_size(self._embedding_entry.size_bytes_approx)})"
        )

    def _build_ui(self) -> None:
        title = toga.Label(
            "Model Setup",
            style=Pack(padding_bottom=10, font_size=16, font_weight="bold"),
        )
        self._box.add(title)

        info = toga.Label(
            "Select a chat model to download. The embedding model is "
            "always included automatically.",
            style=Pack(padding_bottom=10),
        )
        self._box.add(info)

        # Model selector
        default_name = next(
            (e.display_name for e in self._chat_entries if e.is_default),
            self._chat_entries[0].display_name,
        )
        items = [e.display_name for e in self._chat_entries]
        self._selection = toga.Selection(
            items=items,
            value=default_name,
            on_change=self._update_size_label,
            style=Pack(padding_bottom=5),
        )
        self._box.add(self._selection)

        # Size label
        self._size_label = toga.Label("", style=Pack(padding_bottom=10))
        self._box.add(self._size_label)
        self._update_size_label()

        # Download button
        self._download_btn = toga.Button(
            "Download",
            on_press=self._on_download,
            style=Pack(padding_bottom=10),
        )
        self._box.add(self._download_btn)

        # Progress area (hidden until download starts)
        self._progress_box = toga.Box(style=Pack(direction=COLUMN, padding_top=5))

        self._chat_bar_label = toga.Label("", style=Pack(padding_top=5))
        self._progress_box.add(self._chat_bar_label)
        self._chat_bar = toga.ProgressBar(max=1.0, style=Pack(padding_bottom=5, flex=1))
        self._chat_bar.value = 0.0
        self._progress_box.add(self._chat_bar)

        self._embed_bar_label = toga.Label("", style=Pack(padding_top=5))
        self._progress_box.add(self._embed_bar_label)
        self._embed_bar = toga.ProgressBar(max=1.0, style=Pack(padding_bottom=5, flex=1))
        self._embed_bar.value = 0.0
        self._progress_box.add(self._embed_bar)

        self._box.add(self._progress_box)

        # Status label
        self._status_label = toga.Label("", style=Pack(padding_top=10))
        self._box.add(self._status_label)

    def _on_download(self, widget) -> None:
        """Start concurrent model downloads."""
        asyncio.ensure_future(self._run_downloads())

    async def _run_downloads(self) -> None:
        chat_entry = self._selected_chat_entry()

        # Disable controls
        if self._selection:
            self._selection.enabled = False
        if self._download_btn:
            self._download_btn.enabled = False
        if self._status_label:
            self._status_label.text = "Downloading models…"

        # Set bar labels
        if self._chat_bar_label:
            self._chat_bar_label.text = chat_entry.filename
        if self._embed_bar_label:
            self._embed_bar_label.text = self._embedding_entry.filename

        dest_dir = Path(user_data_dir("zforge")) / _MODELS_SUBDIR
        service = ModelDownloadService()

        def _chat_progress(filename: str, received: int, total: int) -> None:
            if self._chat_bar and total > 0:
                self._chat_bar.value = received / total

        def _embed_progress(filename: str, received: int, total: int) -> None:
            if self._embed_bar and total > 0:
                self._embed_bar.value = received / total

        try:
            chat_path, embed_path = await asyncio.gather(
                service.download(chat_entry, dest_dir, _chat_progress),
                service.download(self._embedding_entry, dest_dir, _embed_progress),
            )

            # Persist paths to config
            config_service = self._state.config_service
            if config_service:
                config = config_service.load()
                config.chat_model_path = f"{_MODELS_SUBDIR}/{chat_entry.filename}"
                config.embedding_model_path = f"{_MODELS_SUBDIR}/{self._embedding_entry.filename}"
                config_service.save(config)

            # Reconstruct connectors with new paths
            from zforge.services.embedding.llama_cpp_embedding_connector import (
                LlamaCppEmbeddingConnector,
            )
            from zforge.services.llm.llama_cpp_connector import LlamaCppConnector

            if config_service:
                config = config_service.load()
                self._state.llm_connector = LlamaCppConnector(
                    model_path=config.chat_model_path,
                    context_size=config.chat_context_size,
                    gpu_layers=config.chat_gpu_layers,
                )
                self._state.embedding_connector = LlamaCppEmbeddingConnector(
                    model_path=config.embedding_model_path,
                    context_size=config.embedding_context_size,
                    gpu_layers=config.embedding_gpu_layers,
                )

            if self._status_label:
                self._status_label.text = "Download complete!"

            if self._on_done:
                self._on_done()

        except Exception:
            log.exception("Model download failed")
            if self._status_label:
                self._status_label.text = (
                    "Download failed. Please check your internet connection "
                    "and try again."
                )
            if self._selection:
                self._selection.enabled = True
            if self._download_btn:
                self._download_btn.enabled = True

    @property
    def box(self) -> toga.Box:
        return self._box
