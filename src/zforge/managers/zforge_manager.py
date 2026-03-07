"""ZForge Manager — central coordinator.

Holds singleton instances of ZWorldManager and ExperienceManager.
Constructs and runs LangGraph process graphs, streaming status updates to UI.

Implements: src/zforge/managers/zforge_manager.py per
docs/LLM Orchestration.md and docs/Managers, Processes, and MCP Server.md.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine

log = logging.getLogger(__name__)

from zforge.graphs.experience_generation_graph import (
    build_experience_generation_graph,
)
from zforge.graphs.world_creation_graph import build_create_world_graph
from zforge.managers.experience_manager import ExperienceManager
from zforge.managers.zworld_manager import ZWorldManager
from zforge.models.zforge_config import PlayerPreferences
from zforge.models.zworld import ZWorld
from zforge.services.if_engine.if_engine_connector import IfEngineConnector
from zforge.services.llm.llm_connector import LlmConnector
from zforge.tools.experience_tools import set_if_engine_connector
from zforge.tools.world_tools import set_zworld_manager


class ZForgeManager:
    """Central coordinator for Z-Forge operations."""

    def __init__(
        self,
        zworld_manager: ZWorldManager,
        experience_manager: ExperienceManager,
        llm_connector: LlmConnector,
        if_engine_connector: IfEngineConnector,
    ) -> None:
        self.zworld_manager = zworld_manager
        self.experience_manager = experience_manager
        self._llm_connector = llm_connector
        self._if_engine_connector = if_engine_connector

        # Inject dependencies for tool functions
        set_zworld_manager(zworld_manager)
        set_if_engine_connector(if_engine_connector)

    async def run_process(
        self,
        graph,
        initial_state: dict[str, Any],
        on_status_update: Callable[[str], None] | None = None,
        on_rationale_update: Callable[[str, dict], None] | None = None,
    ) -> dict[str, Any]:
        """Run a LangGraph graph, streaming status_message and rationale updates to the UI."""
        log.info("run_process: starting — initial status=%r", initial_state.get("status"))
        final_state = initial_state
        try:
            async for chunk in graph.astream(initial_state):
                for node_name, node_output in chunk.items():
                    log.debug("run_process: chunk from node=%r output=%r", node_name, node_output)
                    if isinstance(node_output, dict):
                        final_state = {**final_state, **node_output}
                        status = node_output.get("status") or final_state.get("status")
                        msg = node_output.get("status_message")
                        log.info(
                            "run_process: node=%r status=%r message=%r",
                            node_name, status, msg,
                        )
                        if on_status_update and msg:
                            on_status_update(msg)
                        if on_rationale_update and "action_log" in node_output:
                            for entry in node_output["action_log"]:
                                on_rationale_update(entry.get("rationale", ""), entry)
        except Exception as exc:  # surface unexpected errors to caller/UI
            log.exception("run_process: unhandled exception — %s", exc)
            msg = f"Process failed: {exc}"
            final_state = {**final_state, "status": "failed", "failure_reason": str(exc), "status_message": msg}
            if on_status_update:
                try:
                    on_status_update(msg)
                except Exception:
                    pass
        log.info("run_process: finished — final status=%r", final_state.get("status"))
        return final_state

    async def start_world_creation(
        self,
        input_text: str,
        on_status_update: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Run the world creation process."""
        graph = build_create_world_graph(self._llm_connector)
        initial_state = {
            "input_text": input_text,
            "input_valid": None,
            "validation_iterations": 0,
            "status": "awaiting_validation",
            "status_message": "Starting world creation...",
            "failure_reason": None,
            "messages": [],
        }
        return await self.run_process(graph, initial_state, on_status_update)

    async def start_experience_generation(
        self,
        z_world: ZWorld,
        preferences: PlayerPreferences,
        player_prompt: str | None = None,
        on_status_update: Callable[[str], None] | None = None,
        on_rationale_update: Callable[[str, dict], None] | None = None,
    ) -> dict[str, Any]:
        """Run the experience generation process."""
        if on_status_update:
            on_status_update("Initializing IF engine...")
        await self._if_engine_connector.initialize()
        graph = build_experience_generation_graph(
            self._llm_connector, self._if_engine_connector, on_status_update
        )
        initial_state = {
            "z_world": z_world.to_dict(),
            "preferences": preferences.to_dict(),
            "player_prompt": player_prompt,
            "outline": None,
            "tech_notes": None,
            "outline_notes": None,
            "script": None,
            "script_notes": None,
            "tech_edit_report": None,
            "story_edit_report": None,
            "compiled_output": None,
            "compiler_errors": [],
            "outline_iterations": 0,
            "script_compile_iterations": 0,
            "author_review_iterations": 0,
            "tech_edit_iterations": 0,
            "story_edit_iterations": 0,
            "status": "awaiting_outline",
            "status_message": "Starting experience generation...",
            "failure_reason": None,
            "current_rationale": None,
            "action_log": [],
            "messages": [],
        }
        return await self.run_process(graph, initial_state, on_status_update, on_rationale_update)
