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
        self._world_creation_graph = None

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
            async for mode, data in graph.astream(initial_state, stream_mode=["updates", "debug"]):
                if mode == "debug":
                    log.debug(
                        "run_process: [graph:debug] type=%r step=%r payload=%r",
                        data.get("type"),
                        data.get("step"),
                        data.get("payload"),
                    )
                    continue
                # mode == "updates": data is {node_name: node_output}
                for node_name, node_output in data.items():
                    log.debug("run_process: chunk from node=%r output=%r", node_name, node_output)
                    if isinstance(node_output, dict):
                        prev_status = final_state.get("status")
                        final_state = {**final_state, **node_output}
                        new_status = final_state.get("status")
                        status_changed = new_status != prev_status
                        msg = node_output.get("status_message")
                        log.info(
                            "run_process: node=%r  status=%r%s  message=%r",
                            node_name,
                            new_status,
                            f"  (was {prev_status!r})" if status_changed else "",
                            msg,
                        )
                        # Surface interesting state shape so failures are diagnosable
                        if any(k in node_output for k in ("status", "validation_iterations", "partial_zworlds", "current_chunk_index")):
                            partial_count = len(final_state.get("partial_zworlds") or [])
                            chunk_idx = final_state.get("current_chunk_index", 0)
                            chunks_total = len(final_state.get("input_chunks") or [])
                            val_iters = final_state.get("validation_iterations", 0)
                            log.info(
                                "run_process: [%s] validation_iterations=%d  "
                                "chunk=%d/%d  partial_zworlds=%d",
                                node_name, val_iters, chunk_idx, chunks_total, partial_count,
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
        if self._world_creation_graph is None:
            log.info("start_world_creation: building graph (first call)")
            self._world_creation_graph = build_create_world_graph(self._llm_connector)
        graph = self._world_creation_graph
        initial_state = {
            "input_text": input_text,
            "input_valid": None,
            "input_chunks": [],
            "current_chunk_index": 0,
            "partial_zworlds": [],
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
        """Run the experience generation process.

        TODO: Experience generation must be reworked to consume the new
        Z-Bundle world format.  For now this raises NotImplementedError.
        """
        raise NotImplementedError(
            "Experience generation has not yet been updated for the new "
            "Z-Bundle world format. This will be implemented in a future update."
        )
