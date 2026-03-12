"""LLM Configuration Screen.

Full LLM configuration UI with three sections:
  1. Node Configuration — per-process / per-node provider + model selection.
  2. Provider Configuration — API keys for each remote provider.
  3. Local Model — chat + embedding GGUF download with progress bars.

A "Use Defaults" button skips straight to on_done without persisting changes.
"Save" persists node config to ZForgeConfig, API keys to the platform keyring,
and updates the live connectors before calling on_done.

Implements: src/zforge/ui/screens/llm_config_screen.py per
docs/User Experience.md § LLM Configuration and § LLM Connector Configuration.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import flet as ft
import keyring
from platformdirs import user_data_dir

from zforge.models.model_catalogue import CATALOGUE, ModelCatalogueEntry
from zforge.models.process_config import PROCESSES, REMOTE_CONNECTOR_KEYS
from zforge.models.zforge_config import LlmNodeConfig
from zforge.services.model_download_service import ModelDownloadService

if TYPE_CHECKING:
    from zforge.app_state import AppState

log = logging.getLogger(__name__)

_MODELS_SUBDIR = "models"


def _format_size(size_bytes: int) -> str:
    if size_bytes >= 1_000_000_000:
        return f"~{size_bytes / 1_073_741_824:.1f} GB"
    return f"~{size_bytes / 1_048_576:.0f} MB"


class LlmConfigScreen:
    """Full LLM configuration screen (node config + provider keys + local model download)."""

    def __init__(
        self,
        page: ft.Page,
        app_state: "AppState",
        on_done: Callable[[], None] | None = None,
        show_no_config_message: bool = False,
    ) -> None:
        self._page = page
        self._state = app_state
        self._on_done = on_done
        self._show_no_config_message = show_no_config_message

        # (process_slug, node_slug) → {"provider_sel": Dropdown, "model_sel": Dropdown}
        self._node_rows: dict[tuple[str, str], dict[str, ft.Dropdown]] = {}
        # connector_name → TextField (API key)
        self._api_key_inputs: dict[str, ft.TextField] = {}

        self._chat_entries = [e for e in CATALOGUE if e.role == "chat"]
        self._embedding_entry: ModelCatalogueEntry = next(
            e for e in CATALOGUE if e.role == "embedding" and e.is_default
        )
        self._chat_sel: ft.Dropdown | None = None
        self._size_label: ft.Text | None = None
        self._download_btn: ft.ElevatedButton | None = None
        self._chat_bar: ft.ProgressBar | None = None
        self._embed_bar: ft.ProgressBar | None = None
        self._chat_bar_label: ft.Text | None = None
        self._embed_bar_label: ft.Text | None = None
        self._download_status_label: ft.Text | None = None
        self._chunk_size_input: ft.TextField | None = None
        self._chunk_overlap_pct_input: ft.TextField | None = None
        self._retrieval_chunk_size_input: ft.TextField | None = None
        self._retrieval_chunk_overlap_pct_input: ft.TextField | None = None

    def build(self) -> ft.Control:
        controls: list[ft.Control] = []

        controls.append(ft.Text("LLM Configuration", size=18, weight=ft.FontWeight.BOLD))

        if self._show_no_config_message:
            controls.append(
                ft.Text(
                    "No LLM configuration was found. Configure below or press "
                    "\"Use Defaults\" to proceed with default provider settings.",
                )
            )

        controls.extend(self._build_node_section())
        controls.extend(self._build_provider_section())
        controls.extend(self._build_local_model_section())
        controls.extend(self._build_parsing_section())
        controls.extend(self._build_button_row())

        return ft.Column(
            controls,
            spacing=6,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_node_section(self) -> list[ft.Control]:
        registry = self._state.connector_registry
        config_service = self._state.config_service
        config = config_service.load() if config_service else None
        providers = registry.list_names() if registry else []

        controls: list[ft.Control] = [
            ft.Text("Node Configuration", size=14, weight=ft.FontWeight.BOLD),
            ft.Text("Select the provider and model for each process node."),
        ]

        for proc in PROCESSES:
            controls.append(ft.Text(proc.display, weight=ft.FontWeight.BOLD))
            for node in proc.nodes:
                saved_cfg = (
                    config.llm_nodes.get(proc.slug, {}).get(node.slug)
                    if config else None
                )
                init_provider = (
                    saved_cfg.provider
                    if saved_cfg and saved_cfg.provider in providers
                    else (node.default_provider if node.default_provider in providers else (providers[0] if providers else ""))
                )

                connector = registry.get(init_provider) if registry and init_provider else None
                available_models = connector.get_available_models() if connector else []
                init_model = (
                    saved_cfg.model
                    if saved_cfg and saved_cfg.model in available_models
                    else (available_models[0] if available_models else "")
                )

                ps, ns = proc.slug, node.slug
                provider_sel = ft.Dropdown(
                    options=[ft.dropdown.Option(p) for p in providers],
                    value=init_provider if init_provider in providers else None,
                    on_change=lambda e, ps=ps, ns=ns: self._on_provider_change(ps, ns, e),
                    width=180,
                )
                model_sel = ft.Dropdown(
                    options=[ft.dropdown.Option(m) for m in available_models],
                    value=init_model if init_model in available_models else None,
                    width=260,
                )
                controls.append(
                    ft.Row([ft.Text(f"  {node.display}", width=120), provider_sel, model_sel])
                )
                self._node_rows[(ps, ns)] = {"provider_sel": provider_sel, "model_sel": model_sel}

        return controls

    def _build_provider_section(self) -> list[ft.Control]:
        controls: list[ft.Control] = [
            ft.Text("Provider Configuration", size=14, weight=ft.FontWeight.BOLD),
            ft.Text("Enter API keys for remote providers. Leave blank if you are not using that provider."),
        ]

        for name, (svc, key) in REMOTE_CONNECTOR_KEYS.items():
            current_value = keyring.get_password(svc, key) or ""
            text_input = ft.TextField(
                value=current_value,
                hint_text="(not set)",
                expand=True,
            )
            controls.append(
                ft.Row([ft.Text(f"  {name}", width=120), ft.Text("API Key:"), text_input])
            )
            self._api_key_inputs[name] = text_input

        return controls

    def _build_local_model_section(self) -> list[ft.Control]:
        controls: list[ft.Control] = [
            ft.Text("Local Model", size=14, weight=ft.FontWeight.BOLD),
            ft.Text(
                "Select and download a local GGUF chat model. "
                "The embedding model is always included."
            ),
        ]

        default_name = next(
            (e.display_name for e in self._chat_entries if e.is_default),
            self._chat_entries[0].display_name if self._chat_entries else "",
        )
        self._chat_sel = ft.Dropdown(
            options=[ft.dropdown.Option(e.display_name) for e in self._chat_entries],
            value=default_name,
            on_change=self._update_size_label,
        )
        controls.append(self._chat_sel)

        self._size_label = ft.Text("")
        controls.append(self._size_label)
        self._update_size_label()

        self._download_btn = ft.ElevatedButton(
            "Download", on_click=self._on_download
        )
        controls.append(self._download_btn)

        self._chat_bar_label = ft.Text("")
        controls.append(self._chat_bar_label)
        self._chat_bar = ft.ProgressBar(value=0, expand=True)
        controls.append(self._chat_bar)

        self._embed_bar_label = ft.Text("")
        controls.append(self._embed_bar_label)
        self._embed_bar = ft.ProgressBar(value=0, expand=True)
        controls.append(self._embed_bar)

        self._download_status_label = ft.Text("")
        controls.append(self._download_status_label)

        return controls

    def _build_parsing_section(self) -> list[ft.Control]:
        config_service = self._state.config_service
        config = config_service.load() if config_service else None
        chunk_size = config.parsing_chunk_size if config else 10000
        chunk_overlap = config.parsing_chunk_overlap if config else 500
        overlap_pct = round(chunk_overlap / chunk_size * 100) if chunk_size else 5

        self._chunk_size_input = ft.TextField(value=str(chunk_size), width=100)
        self._chunk_overlap_pct_input = ft.TextField(value=str(overlap_pct), width=60)

        retrieval_size = config.parsing_retrieval_chunk_size if config else 500
        retrieval_overlap_abs = config.parsing_retrieval_chunk_overlap if config else 50
        retrieval_overlap_pct = round(retrieval_overlap_abs / retrieval_size * 100) if retrieval_size else 10

        self._retrieval_chunk_size_input = ft.TextField(value=str(retrieval_size), width=100)
        self._retrieval_chunk_overlap_pct_input = ft.TextField(value=str(retrieval_overlap_pct), width=60)

        return [
            ft.Text("Parsing Pipeline", size=14, weight=ft.FontWeight.BOLD),
            ft.Text("Controls how source documents are split before LLM processing."),
            ft.Row([ft.Text("Chunk size:", width=160), self._chunk_size_input, ft.Text("characters")]),
            ft.Row([ft.Text("Chunk overlap:", width=160), self._chunk_overlap_pct_input, ft.Text("% of chunk size")]),
            ft.Text(
                "Retrieval split: each context chunk is re-split to the size below for the vector store.",
            ),
            ft.Row([ft.Text("Retrieval chunk size:", width=160), self._retrieval_chunk_size_input, ft.Text("characters")]),
            ft.Row([ft.Text("Retrieval overlap:", width=160), self._retrieval_chunk_overlap_pct_input, ft.Text("% of retrieval chunk size")]),
        ]

    def _build_button_row(self) -> list[ft.Control]:
        return [
            ft.Row([
                ft.ElevatedButton("Use Defaults", on_click=self._on_use_defaults),
                ft.ElevatedButton("Save", on_click=self._on_save),
            ]),
        ]

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_provider_change(self, process_slug: str, node_slug: str, e: ft.ControlEvent) -> None:
        """Refresh the model list when a node's provider changes."""
        row = self._node_rows.get((process_slug, node_slug))
        if row is None:
            return
        provider = e.control.value
        registry = self._state.connector_registry
        connector = registry.get(provider) if registry and provider else None
        models = connector.get_available_models() if connector else []
        model_sel = row["model_sel"]
        model_sel.options = [ft.dropdown.Option(m) for m in models]
        model_sel.value = models[0] if models else None
        self._page.update()

    def _update_size_label(self, e: ft.ControlEvent | None = None) -> None:
        if self._size_label is None or self._chat_sel is None:
            return
        chat = self._selected_chat_entry()
        total = chat.size_bytes_approx + self._embedding_entry.size_bytes_approx
        self._size_label.value = (
            f"Total download: {_format_size(total)}"
            f" (chat {_format_size(chat.size_bytes_approx)}"
            f" + embedding {_format_size(self._embedding_entry.size_bytes_approx)})"
        )
        if e is not None:
            self._page.update()

    def _selected_chat_entry(self) -> ModelCatalogueEntry:
        if self._chat_sel is None:
            return self._chat_entries[0]
        name = self._chat_sel.value
        for entry in self._chat_entries:
            if entry.display_name == name:
                return entry
        return self._chat_entries[0]

    def _on_download(self, e: ft.ControlEvent) -> None:
        self._page.run_task(self._run_downloads)

    async def _run_downloads(self) -> None:
        chat_entry = self._selected_chat_entry()
        if self._chat_sel:
            self._chat_sel.disabled = True
        if self._download_btn:
            self._download_btn.disabled = True
        if self._download_status_label:
            self._download_status_label.value = "Downloading models…"
        if self._chat_bar_label:
            self._chat_bar_label.value = chat_entry.filename
        if self._embed_bar_label:
            self._embed_bar_label.value = self._embedding_entry.filename
        self._page.update()

        dest_dir = Path(user_data_dir("zforge")) / _MODELS_SUBDIR
        service = ModelDownloadService()

        def _chat_progress(filename: str, received: int, total: int) -> None:
            if self._chat_bar and total > 0:
                self._chat_bar.value = received / total
                self._page.update()

        def _embed_progress(filename: str, received: int, total: int) -> None:
            if self._embed_bar and total > 0:
                self._embed_bar.value = received / total
                self._page.update()

        try:
            await asyncio.gather(
                service.download(chat_entry, dest_dir, _chat_progress),
                service.download(self._embedding_entry, dest_dir, _embed_progress),
            )
            config_service = self._state.config_service
            if config_service:
                config = config_service.load()
                config.chat_model_path = f"{_MODELS_SUBDIR}/{chat_entry.filename}"
                config.embedding_model_path = f"{_MODELS_SUBDIR}/{self._embedding_entry.filename}"
                config_service.save(config)

                from zforge.services.embedding.llama_cpp_embedding_connector import (
                    LlamaCppEmbeddingConnector,
                )
                from zforge.services.llm.llama_cpp_connector import LlamaCppConnector

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

            if self._download_status_label:
                self._download_status_label.value = "Download complete!"
            self._page.update()

            if self._on_done:
                self._on_done()

        except Exception:
            log.exception("Model download failed")
            if self._download_status_label:
                self._download_status_label.value = (
                    "Download failed. Check your internet connection and try again."
                )
            if self._chat_sel:
                self._chat_sel.disabled = False
            if self._download_btn:
                self._download_btn.disabled = False
            self._page.update()

    def _on_use_defaults(self, e: ft.ControlEvent) -> None:
        """Proceed without saving any changes."""
        if self._on_done:
            self._on_done()

    def _on_save(self, e: ft.ControlEvent) -> None:
        """Persist node config + API keys then proceed."""
        config_service = self._state.config_service
        registry = self._state.connector_registry

        if config_service:
            config = config_service.load()
            for (process_slug, node_slug), row in self._node_rows.items():
                provider = row["provider_sel"].value or ""
                model = row["model_sel"].value or ""
                config.llm_nodes.setdefault(process_slug, {})[node_slug] = LlmNodeConfig(
                    provider=provider, model=model
                )
            if self._chunk_size_input and self._chunk_overlap_pct_input:
                try:
                    chunk_size = max(1, int(self._chunk_size_input.value or "10000"))
                    overlap_pct = max(0, min(99, int(self._chunk_overlap_pct_input.value or "5")))
                    config.parsing_chunk_size = chunk_size
                    config.parsing_chunk_overlap = round(chunk_size * overlap_pct / 100)
                except ValueError:
                    pass
            if self._retrieval_chunk_size_input and self._retrieval_chunk_overlap_pct_input:
                try:
                    retrieval_size = max(1, int(self._retrieval_chunk_size_input.value or "500"))
                    retrieval_overlap_pct = max(
                        0, min(99, int(self._retrieval_chunk_overlap_pct_input.value or "10"))
                    )
                    config.parsing_retrieval_chunk_size = retrieval_size
                    config.parsing_retrieval_chunk_overlap = round(
                        retrieval_size * retrieval_overlap_pct / 100
                    )
                except ValueError:
                    pass
            config_service.save(config)

        for connector_name, text_input in self._api_key_inputs.items():
            value = (text_input.value or "").strip()
            if not value:
                continue
            if registry:
                connector = registry.get(connector_name)
                if connector and hasattr(connector, "set_api_key"):
                    connector.set_api_key(value)
            else:
                svc, key = REMOTE_CONNECTOR_KEYS[connector_name]
                keyring.set_password(svc, key, value)

        # Push the updated config into the live manager so cached graphs are
        # rebuilt with the new provider/model settings on next use.
        mgr = self._state.zforge_manager
        if mgr is not None and config_service:
            mgr.update_config(config_service.load())

        if self._on_done:
            self._on_done()
