"""Z-Forge BeeWare Application.

ZForgeApp(toga.App) — startup flow: load config, check local model files,
show LLM config screen if missing or home screen if ready.

Implements: src/zforge/app.py per docs/User Experience.md.
"""

from __future__ import annotations

import asyncio
import logging

import toga

log = logging.getLogger(__name__)

from zforge.app_state import AppState
from zforge.managers.experience_manager import ExperienceManager
from zforge.managers.zforge_manager import ZForgeManager
from zforge.managers.zworld_manager import ZWorldManager
from zforge.services.config_service import ConfigService
from zforge.services.embedding.llama_cpp_embedding_connector import (
    LlamaCppEmbeddingConnector,
)
from zforge.services.if_engine.ink_engine_connector import InkEngineConnector
from zforge.services.llm.anthropic_connector import AnthropicConnector
from zforge.services.llm.connector_registry import ConnectorRegistry
from zforge.services.llm.google_connector import GoogleConnector
from zforge.services.llm.groq_connector import GroqConnector
from zforge.services.llm.llama_cpp_connector import LlamaCppConnector
from zforge.services.llm.openai_connector import OpenAiConnector


class ZForgeApp(toga.App):
    """Main Z-Forge application."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._app_state = AppState()

    def startup(self) -> None:
        self.main_window = toga.MainWindow(title=self.formal_name)

        # Initialize services
        config_service = ConfigService()
        config_exists = config_service.exists()
        has_llm_config = config_service.has_llm_config()
        config = config_service.load()

        self._app_state.config_service = config_service

        # Initialize LLM connector registry with all available connectors
        registry = ConnectorRegistry()

        # Local connector (llama.cpp)
        llm_connector = LlamaCppConnector(
            model_path=config.chat_model_path,
            context_size=config.chat_context_size,
            gpu_layers=config.chat_gpu_layers,
        )
        registry.register(llm_connector)

        # Remote connectors — load credentials from keyring
        openai_connector = OpenAiConnector()
        openai_connector.load_from_keyring()
        registry.register(openai_connector)

        google_connector = GoogleConnector()
        google_connector.load_from_keyring()
        registry.register(google_connector)

        anthropic_connector = AnthropicConnector()
        anthropic_connector.load_from_keyring()
        registry.register(anthropic_connector)

        groq_connector = GroqConnector()
        groq_connector.load_from_keyring()
        registry.register(groq_connector)

        # OpenAI is the default provider for world generation
        registry.set_default("OpenAI")

        self._app_state.llm_connector = llm_connector
        self._app_state.connector_registry = registry

        # Initialize embedding connector
        embedding_connector = LlamaCppEmbeddingConnector(
            model_path=config.embedding_model_path,
            context_size=config.embedding_context_size,
            gpu_layers=config.embedding_gpu_layers,
        )
        self._app_state.embedding_connector = embedding_connector

        # Initialize IF engine connector and pre-warm in background
        if_engine = InkEngineConnector()
        self._app_state.if_engine_connector = if_engine
        asyncio.ensure_future(self._prewarm_if_engine(if_engine))

        # Initialize managers
        zworld_manager = ZWorldManager(config.bundles_root, embedding_connector)
        experience_manager = ExperienceManager(
            config.experience_folder, if_engine
        )
        zforge_manager = ZForgeManager(
            zworld_manager=zworld_manager,
            experience_manager=experience_manager,
            llm_connector=llm_connector,
            connector_registry=registry,
            config=config,
            if_engine_connector=if_engine,
            embedding_connector=embedding_connector,
        )
        self._app_state.zforge_manager = zforge_manager

        # Show LLM config on first run (no file) or no llm_nodes section;
        # also show if either local connector is broken.
        if not config_exists or not has_llm_config:
            self._show_llm_config(show_no_config_message=True)
        elif llm_connector.validate() and embedding_connector.validate():
            asyncio.ensure_future(self._prewarm_llm(llm_connector))
            asyncio.ensure_future(self._prewarm_embedding(embedding_connector))
            self._show_home()
        else:
            self._show_llm_config(show_no_config_message=False)

        self.main_window.show()

    async def _prewarm_if_engine(self, if_engine: InkEngineConnector) -> None:
        """Initialize IF engine eagerly in background so it's ready by the time the user generates."""
        log.info("_prewarm_if_engine: starting InkEngineConnector initialization")
        try:
            await if_engine.initialize()
            log.info("_prewarm_if_engine: InkEngineConnector ready")
        except Exception:
            log.exception("_prewarm_if_engine: initialization failed")

    async def _prewarm_llm(self, llm_connector) -> None:
        """Load the LLM in a background thread so it is cached before first use."""
        log.info("_prewarm_llm: loading LLM model in background thread")
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, llm_connector.get_model)
            log.info("_prewarm_llm: LLM model ready")
        except Exception:
            log.exception("_prewarm_llm: LLM model load failed")

    async def _prewarm_embedding(self, embedding_connector) -> None:
        """Load the embedding model in a background thread so it is cached before first use."""
        log.info("_prewarm_embedding: loading embedding model in background thread")
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, embedding_connector.get_embeddings)
            log.info("_prewarm_embedding: embedding model ready")
        except Exception:
            log.exception("_prewarm_embedding: embedding model load failed")

    def _show_home(self) -> None:
        from zforge.ui.screens.home_screen import HomeScreen

        screen = HomeScreen(self, self._app_state)
        screen.refresh()
        self.main_window.content = screen.box

    def _show_llm_config(self, show_no_config_message: bool = False) -> None:
        from zforge.ui.screens.llm_config_screen import LlmConfigScreen

        screen = LlmConfigScreen(
            self, self._app_state, on_done=self._show_home,
            show_no_config_message=show_no_config_message,
        )
        self.main_window.content = screen.box
