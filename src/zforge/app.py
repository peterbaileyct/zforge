"""Z-Forge BeeWare Application.

ZForgeApp(toga.App) — startup flow: load config, check LLM credentials,
show appropriate screen.

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
from zforge.services.if_engine.ink_engine_connector import InkEngineConnector
from zforge.services.llm.openai_connector import OpenAiConnector
from zforge.services.secure_config_service import SecureConfigService


class ZForgeApp(toga.App):
    """Main Z-Forge application."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._app_state = AppState()

    def startup(self) -> None:
        self.main_window = toga.MainWindow(title=self.formal_name)

        # Initialize services
        config_service = ConfigService()
        secure_config_service = SecureConfigService()
        config = config_service.load()

        self._app_state.config_service = config_service
        self._app_state.secure_config_service = secure_config_service

        # Initialize LLM connector
        llm_connector = OpenAiConnector()
        llm_connector.load_from_keyring()
        self._app_state.llm_connector = llm_connector

        # Initialize IF engine connector and pre-warm in background
        if_engine = InkEngineConnector()
        self._app_state.if_engine_connector = if_engine
        asyncio.ensure_future(self._prewarm_if_engine(if_engine))

        # Initialize managers
        zworld_manager = ZWorldManager(config.zworld_folder)
        experience_manager = ExperienceManager(
            config.experience_folder, if_engine
        )
        zforge_manager = ZForgeManager(
            zworld_manager=zworld_manager,
            experience_manager=experience_manager,
            llm_connector=llm_connector,
            if_engine_connector=if_engine,
        )
        self._app_state.zforge_manager = zforge_manager

        # Check LLM credentials and show appropriate screen
        if llm_connector.validate():
            self._show_home()
        else:
            self._show_llm_config()

        self.main_window.show()

    async def _prewarm_if_engine(self, if_engine: InkEngineConnector) -> None:
        """Initialize IF engine eagerly in background so it's ready by the time the user generates."""
        log.info("_prewarm_if_engine: starting InkEngineConnector initialization")
        try:
            await if_engine.initialize()
            log.info("_prewarm_if_engine: InkEngineConnector ready")
        except Exception:
            log.exception("_prewarm_if_engine: initialization failed")

    def _show_home(self) -> None:
        from zforge.ui.screens.home_screen import HomeScreen

        screen = HomeScreen(self, self._app_state)
        screen.refresh()
        self.main_window.content = screen.box

    def _show_llm_config(self) -> None:
        from zforge.ui.screens.llm_config_screen import LlmConfigScreen

        screen = LlmConfigScreen(
            self, self._app_state, on_done=self._show_home
        )
        self.main_window.content = screen.box
