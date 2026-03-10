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
from zforge.models.zforge_config import PlayerPreferences, ZForgeConfig
from zforge.models.zworld import ZWorld
from zforge.services.embedding.embedding_connector import EmbeddingConnector
from zforge.services.if_engine.if_engine_connector import IfEngineConnector
from zforge.services.llm.connector_registry import ConnectorRegistry
from zforge.services.llm.llm_connector import LlmConnector
from zforge.tools.world_tools import set_zworld_manager


class ZForgeManager:
    """Central coordinator for Z-Forge operations."""

    def __init__(
        self,
        zworld_manager: ZWorldManager,
        experience_manager: ExperienceManager,
        llm_connector: LlmConnector,
        connector_registry: ConnectorRegistry,
        config: ZForgeConfig,
        if_engine_connector: IfEngineConnector,
        embedding_connector: EmbeddingConnector,
    ) -> None:
        self.zworld_manager = zworld_manager
        self.experience_manager = experience_manager
        self._llm_connector = llm_connector
        self._connector_registry = connector_registry
        self._config = config
        self._if_engine_connector = if_engine_connector
        self._embedding_connector = embedding_connector
        self._world_creation_graph = None

        # Inject dependencies for tool functions
        set_zworld_manager(zworld_manager)
        from zforge.tools.experience_tools import set_if_engine_connector
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

    def update_config(self, config: ZForgeConfig) -> None:
        """Refresh runtime config and invalidate cached graphs.

        Call this after the user saves LLM configuration so the next world
        creation (or other graph-backed process) picks up the new settings.
        """
        self._config = config
        self._world_creation_graph = None
        log.info("update_config: config refreshed, world creation graph reset")

    def _resolve_node_connector(
        self, process_slug: str, node_slug: str
    ) -> tuple[LlmConnector, str | None]:
        """Resolve the LlmConnector and model name for a specific graph node.

        Falls back to the default connector when the configured provider
        is not found in the registry.
        """
        wg_nodes = self._config.llm_nodes.get(process_slug, {})
        node_cfg = wg_nodes.get(node_slug)
        if node_cfg and node_cfg.provider:
            connector = self._connector_registry.get(node_cfg.provider)
            if connector is not None:
                model = node_cfg.model or None
                log.info(
                    "_resolve_node_connector: %s.%s → provider=%r model=%r",
                    process_slug, node_slug, node_cfg.provider, model,
                )
                return connector, model
            log.warning(
                "_resolve_node_connector: configured provider %r for %s.%s "
                "not found in registry — falling back to default",
                node_cfg.provider, process_slug, node_slug,
            )
        return self._connector_registry.get_default(), None

    async def start_world_creation(
        self,
        input_text: str,
        on_status_update: Callable[[str], None] | None = None,
        on_confirm_duplicate: Callable[
            [str, str], Coroutine
        ] | None = None,
    ) -> dict[str, Any]:
        """Run the world creation process.

        Parameters
        ----------
        input_text:
            The raw world-bible text supplied by the user.
        on_status_update:
            Optional callback for streaming status messages to the UI.
        on_confirm_duplicate:
            Optional async callback invoked when a world with the same title
            already exists.  Receives ``(new_title, conflicting_slug)`` and
            must return ``"overwrite"`` or ``"cancel"``.
        """
        if self._world_creation_graph is None:
            log.info("start_world_creation: building graph (first call)")
            # Resolve connectors for document_parsing sub-graph
            ctx_connector, ctx_model = self._resolve_node_connector(
                "document_parsing", "contextualizer"
            )
            gext_connector, gext_model = self._resolve_node_connector(
                "document_parsing", "graph_extractor"
            )
            # Resolve connector for world_generation summarizer
            sum_connector, sum_model = self._resolve_node_connector(
                "world_generation", "summarizer"
            )
            self._world_creation_graph = build_create_world_graph(
                summarizer_connector=sum_connector,
                contextualizer_connector=ctx_connector,
                graph_extractor_connector=gext_connector,
                embedding_connector=self._embedding_connector,
                zworld_manager=self.zworld_manager,
                config=self._config,
                bundles_root=self._config.bundles_root,
                summarizer_model=sum_model,
                contextualizer_model=ctx_model,
                graph_extractor_model=gext_model,
            )
        graph = self._world_creation_graph
        initial_state = {
            "input_text": input_text,
            "world_uuid": None,
            "z_bundle_root": None,
            "zworld_kvp": None,
            "conflicting_slug": None,
            "overwrite_decision": None,
            "status": "parsing",
            "status_message": "Starting world creation...",
            "failure_reason": None,
            "messages": [],
        }
        result = await self.run_process(graph, initial_state, on_status_update)

        if result.get("status") == "awaiting_confirmation":
            if on_confirm_duplicate is None:
                # No handler provided — default to cancel.
                log.warning(
                    "start_world_creation: duplicate detected but no "
                    "on_confirm_duplicate callback — cancelling"
                )
                return {
                    **result,
                    "status": "cancelled",
                    "status_message": "World creation cancelled: duplicate title detected.",
                }

            kvp = result.get("zworld_kvp") or {}
            new_title = kvp.get("title", "")
            conflicting_slug = result.get("conflicting_slug", "")
            decision = await on_confirm_duplicate(new_title, conflicting_slug)
            log.info(
                "start_world_creation: duplicate decision=%r for title=%r",
                decision,
                new_title,
            )

            # Resume the graph with the decision; skip expensive nodes by
            # forwarding the already-computed z_bundle_root and zworld_kvp.
            resume_state = {
                **result,
                "overwrite_decision": decision,
                "messages": [],  # reset to avoid spurious add_messages accumulation
                "status": "resuming",
                "status_message": f"Resuming world creation with decision: {decision}",
            }
            result = await self.run_process(graph, resume_state, on_status_update)

        return result

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

    async def ask_about_world(self, slug: str, question: str) -> str:
        """Answer a question about a world using agentic RAG.

        Resolves the Librarian node's LLM connector, then delegates to
        ``ZWorldManager.ask()``.

        Parameters
        ----------
        slug:
            Z-World slug identifying the Z-Bundle.
        question:
            Raw user question text.

        Returns
        -------
        str
            Plain-text answer string.
        """
        lib_connector, lib_model = self._resolve_node_connector(
            "ask_about_world", "librarian"
        )
        return await self.zworld_manager.ask(
            slug, question, lib_connector, model_name=lib_model
        )
