"""Application state container.

Holds singleton references to all managers and services.
Implements: src/zforge/app_state.py per docs/User Experience.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zforge.managers.zforge_manager import ZForgeManager
    from zforge.services.config_service import ConfigService
    from zforge.services.embedding.embedding_connector import EmbeddingConnector
    from zforge.services.if_engine.if_engine_connector import IfEngineConnector
    from zforge.services.llm.connector_registry import ConnectorRegistry
    from zforge.services.llm.llm_connector import LlmConnector


@dataclass
class AppState:
    """Global application state shared across UI screens."""

    zforge_manager: ZForgeManager | None = None
    config_service: ConfigService | None = None
    llm_connector: LlmConnector | None = None
    connector_registry: ConnectorRegistry | None = None
    if_engine_connector: IfEngineConnector | None = None
    embedding_connector: EmbeddingConnector | None = None
