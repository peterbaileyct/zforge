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

import keyring
import toga
from platformdirs import user_data_dir
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

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


def _section_label(text: str) -> toga.Label:
    return toga.Label(
        text,
        style=Pack(padding_top=14, padding_bottom=4, font_size=14, font_weight="bold"),
    )


def _sub_label(text: str, **kwargs) -> toga.Label:
    return toga.Label(text, style=Pack(**kwargs))


class LlmConfigScreen:
    """Full LLM configuration screen (node config + provider keys + local model download)."""

    def __init__(
        self,
        app: toga.App,
        app_state: "AppState",
        on_done: Callable[[], None] | None = None,
        show_no_config_message: bool = False,
    ) -> None:
        self._app = app
        self._state = app_state
        self._on_done = on_done
        self._show_no_config_message = show_no_config_message

        # (process_slug, node_slug) → {"provider_sel": Selection, "model_sel": Selection}
        self._node_rows: dict[tuple[str, str], dict[str, toga.Selection]] = {}
        # connector_name → TextInput (API key)
        self._api_key_inputs: dict[str, toga.TextInput] = {}

        self._chat_entries = [e for e in CATALOGUE if e.role == "chat"]
        self._embedding_entry: ModelCatalogueEntry = next(
            e for e in CATALOGUE if e.role == "embedding" and e.is_default
        )
        self._chat_sel: toga.Selection | None = None
        self._size_label: toga.Label | None = None
        self._download_btn: toga.Button | None = None
        self._chat_bar: toga.ProgressBar | None = None
        self._embed_bar: toga.ProgressBar | None = None
        self._chat_bar_label: toga.Label | None = None
        self._embed_bar_label: toga.Label | None = None
        self._download_status_label: toga.Label | None = None

        self._outer = toga.Box(style=Pack(direction=COLUMN, padding=10))
        self._scroll = toga.ScrollContainer(
            content=self._outer,
            style=Pack(flex=1),
        )
        self._root = toga.Box(style=Pack(direction=COLUMN))
        self._root.add(self._scroll)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._outer.add(
            toga.Label(
                "LLM Configuration",
                style=Pack(padding_bottom=6, font_size=18, font_weight="bold"),
            )
        )

        if self._show_no_config_message:
            self._outer.add(
                toga.Label(
                    "No LLM configuration was found. Configure below or press "
                    "\"Use Defaults\" to proceed with default provider settings.",
                    style=Pack(padding_bottom=8),
                )
            )

        self._build_node_section()
        self._build_provider_section()
        self._build_local_model_section()
        self._build_button_row()

    def _build_node_section(self) -> None:
        registry = self._state.connector_registry
        config_service = self._state.config_service
        config = config_service.load() if config_service else None
        providers = registry.list_names() if registry else []

        self._outer.add(_section_label("Node Configuration"))
        self._outer.add(
            _sub_label(
                "Select the provider and model for each process node.",
                padding_bottom=6,
            )
        )

        for proc in PROCESSES:
            self._outer.add(
                _sub_label(proc.display, font_weight="bold", padding_top=6, padding_bottom=2)
            )
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

                row_box = toga.Box(style=Pack(direction=ROW, padding_bottom=4))
                row_box.add(toga.Label(f"  {node.display}", style=Pack(width=100, padding_right=8)))

                ps, ns = proc.slug, node.slug
                provider_sel = toga.Selection(
                    items=providers,
                    value=init_provider if providers else None,
                    on_change=lambda w, ps=ps, ns=ns: self._on_provider_change(ps, ns, w),
                    style=Pack(width=160, padding_right=8),
                )
                model_sel = toga.Selection(
                    items=available_models,
                    value=init_model if available_models else None,
                    style=Pack(width=240),
                )
                row_box.add(provider_sel)
                row_box.add(model_sel)
                self._outer.add(row_box)
                self._node_rows[(ps, ns)] = {"provider_sel": provider_sel, "model_sel": model_sel}

    def _build_provider_section(self) -> None:
        self._outer.add(_section_label("Provider Configuration"))
        self._outer.add(
            _sub_label(
                "Enter API keys for remote providers. Leave blank if you are not using that provider.",
                padding_bottom=6,
            )
        )

        for name, (svc, key) in REMOTE_CONNECTOR_KEYS.items():
            current_value = keyring.get_password(svc, key) or ""
            row_box = toga.Box(style=Pack(direction=ROW, padding_bottom=4, flex=1))
            row_box.add(toga.Label(f"  {name}", style=Pack(width=100, padding_right=8)))
            row_box.add(toga.Label("API Key:", style=Pack(padding_right=6)))
            text_input = toga.TextInput(
                value=current_value,
                placeholder="(not set)",
                style=Pack(flex=1),
            )
            row_box.add(text_input)
            self._outer.add(row_box)
            self._api_key_inputs[name] = text_input

    def _build_local_model_section(self) -> None:
        self._outer.add(_section_label("Local Model"))
        self._outer.add(
            _sub_label(
                "Select and download a local GGUF chat model. "
                "The embedding model is always included.",
                padding_bottom=6,
            )
        )

        default_name = next(
            (e.display_name for e in self._chat_entries if e.is_default),
            self._chat_entries[0].display_name if self._chat_entries else "",
        )
        self._chat_sel = toga.Selection(
            items=[e.display_name for e in self._chat_entries],
            value=default_name,
            on_change=self._update_size_label,
            style=Pack(padding_bottom=4),
        )
        self._outer.add(self._chat_sel)

        self._size_label = toga.Label("", style=Pack(padding_bottom=6))
        self._outer.add(self._size_label)
        self._update_size_label()

        self._download_btn = toga.Button(
            "Download",
            on_press=self._on_download,
            style=Pack(padding_bottom=8),
        )
        self._outer.add(self._download_btn)

        self._chat_bar_label = toga.Label("", style=Pack(padding_top=2))
        self._outer.add(self._chat_bar_label)
        self._chat_bar = toga.ProgressBar(max=1.0, style=Pack(padding_bottom=4, flex=1))
        self._chat_bar.value = 0.0
        self._outer.add(self._chat_bar)

        self._embed_bar_label = toga.Label("", style=Pack(padding_top=2))
        self._outer.add(self._embed_bar_label)
        self._embed_bar = toga.ProgressBar(max=1.0, style=Pack(padding_bottom=4, flex=1))
        self._embed_bar.value = 0.0
        self._outer.add(self._embed_bar)

        self._download_status_label = toga.Label("", style=Pack(padding_top=4))
        self._outer.add(self._download_status_label)

    def _build_button_row(self) -> None:
        btn_row = toga.Box(style=Pack(direction=ROW, padding_top=14, padding_bottom=10))
        btn_row.add(
            toga.Button(
                "Use Defaults",
                on_press=self._on_use_defaults,
                style=Pack(padding_right=10),
            )
        )
        btn_row.add(toga.Button("Save", on_press=self._on_save))
        self._outer.add(btn_row)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_provider_change(self, process_slug: str, node_slug: str, widget) -> None:
        """Refresh the model list when a node's provider changes."""
        row = self._node_rows.get((process_slug, node_slug))
        if row is None:
            return
        provider = widget.value
        registry = self._state.connector_registry
        connector = registry.get(provider) if registry and provider else None
        models = connector.get_available_models() if connector else []
        model_sel = row["model_sel"]
        model_sel.items = models
        if models:
            model_sel.value = models[0]

    def _update_size_label(self, widget=None) -> None:
        if self._size_label is None or self._chat_sel is None:
            return
        chat = self._selected_chat_entry()
        total = chat.size_bytes_approx + self._embedding_entry.size_bytes_approx
        self._size_label.text = (
            f"Total download: {_format_size(total)}"
            f" (chat {_format_size(chat.size_bytes_approx)}"
            f" + embedding {_format_size(self._embedding_entry.size_bytes_approx)})"
        )

    def _selected_chat_entry(self) -> ModelCatalogueEntry:
        if self._chat_sel is None:
            return self._chat_entries[0]
        name = self._chat_sel.value
        for e in self._chat_entries:
            if e.display_name == name:
                return e
        return self._chat_entries[0]

    def _on_download(self, widget) -> None:
        asyncio.ensure_future(self._run_downloads())

    async def _run_downloads(self) -> None:
        chat_entry = self._selected_chat_entry()
        if self._chat_sel:
            self._chat_sel.enabled = False
        if self._download_btn:
            self._download_btn.enabled = False
        if self._download_status_label:
            self._download_status_label.text = "Downloading models…"
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
                self._download_status_label.text = "Download complete!"

            if self._on_done:
                self._on_done()

        except Exception:
            log.exception("Model download failed")
            if self._download_status_label:
                self._download_status_label.text = (
                    "Download failed. Check your internet connection and try again."
                )
            if self._chat_sel:
                self._chat_sel.enabled = True
            if self._download_btn:
                self._download_btn.enabled = True

    def _on_use_defaults(self, widget) -> None:
        """Proceed without saving any changes."""
        if self._on_done:
            self._on_done()

    def _on_save(self, widget) -> None:
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

        if self._on_done:
            self._on_done()

    # ------------------------------------------------------------------

    @property
    def box(self) -> toga.Box:
        return self._root
