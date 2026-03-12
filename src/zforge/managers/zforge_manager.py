"""ZForge Manager — central coordinator.

Holds singleton instances of ZWorldManager and ExperienceManager.
Constructs and runs LangGraph process graphs, streaming status updates to UI.

Implements: src/zforge/managers/zforge_manager.py per
docs/LLM Orchestration.md and docs/Managers, Processes, and MCP Server.md.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

from zforge.graphs.experience_generation_graph import (
    build_experience_generation_graph,
)
from zforge.graphs.world_creation_graph import build_create_world_graph
from zforge.managers.experience_manager import ExperienceManager
from zforge.managers.zworld_manager import ZWorldManager
from zforge.models.zforge_config import ZForgeConfig
from zforge.models.results import Experience
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
        self._experience_generation_graph = None

        # Inject dependencies for tool functions
        set_zworld_manager(zworld_manager)

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
        self._experience_generation_graph = None
        log.info("update_config: config refreshed, cached graphs reset")

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
        on_progress: Callable[[str], None] | None = None,
        on_confirm_duplicate: Callable[
            [str], Awaitable[str]
        ] | None = None,
    ) -> ZWorld | None:
        """Run the world creation process.

        Parameters
        ----------
        input_text:
            The raw world-bible text supplied by the user.
        on_progress:
            Optional callback for streaming status messages to the UI.
        on_confirm_duplicate:
            Optional async callback invoked when a world with the same title
            already exists.  Receives the ``conflicting_slug`` and must return
            ``"overwrite"`` or ``"cancel"``.
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
        result = await self.run_process(graph, initial_state, on_progress)

        if result.get("status") == "awaiting_confirmation":
            if on_confirm_duplicate is None:
                log.warning(
                    "start_world_creation: duplicate detected but no "
                    "on_confirm_duplicate callback — cancelling"
                )
                return None

            conflicting_slug = result.get("conflicting_slug", "")
            decision = await on_confirm_duplicate(conflicting_slug)
            log.info(
                "start_world_creation: duplicate decision=%r for slug=%r",
                decision,
                conflicting_slug,
            )

            if decision != "overwrite":
                return None

            resume_state = {
                **result,
                "overwrite_decision": decision,
                "messages": [],
                "status": "resuming",
                "status_message": f"Resuming world creation with decision: {decision}",
            }
            result = await self.run_process(graph, resume_state, on_progress)

        if result.get("status") == "complete":
            kvp = result.get("zworld_kvp")
            if kvp:
                return ZWorld(**kvp) if isinstance(kvp, dict) else kvp
        return None

    async def start_experience_generation(
        self,
        world_slug: str,
        player_prompt: str | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> Experience | None:
        """Run the experience generation process.

        Parameters
        ----------
        world_slug:
            Slug of the Z-World to generate an experience for.
        player_prompt:
            Optional player prompt / scenario seed.
        on_progress:
            Optional callback for streaming status messages to the UI.

        Returns
        -------
        Experience | None
            The saved Experience on success, or None on failure.
        """
        log.info("start_experience_generation: ENTERED  world_slug=%r", world_slug)
        # Load world data
        zworld = self.zworld_manager.read(world_slug)
        log.info("start_experience_generation: read zworld=%r", zworld)
        zworld_kvp = zworld.model_dump() if hasattr(zworld, "model_dump") else dataclasses.asdict(zworld)
        z_bundle_root = str(self.zworld_manager._world_root(world_slug))
        log.info("start_experience_generation: z_bundle_root=%r", z_bundle_root)

        # Build graph (cached)
        if self._experience_generation_graph is None:
            log.info("start_experience_generation: building graph (first call)")
            node_slugs = [
                "outline_author", "outline_reviewer",
                "prose_writer", "prose_reviewer",
                "ink_scripter", "ink_debugger",
                "ink_qa", "ink_auditor",
            ]
            connectors: dict[str, tuple] = {}
            for ns in node_slugs:
                conn, model = self._resolve_node_connector("experience_generation", ns)
                connectors[ns] = (conn, model)

            self._experience_generation_graph = build_experience_generation_graph(
                outline_author_connector=connectors["outline_author"][0],
                outline_author_model=connectors["outline_author"][1],
                outline_reviewer_connector=connectors["outline_reviewer"][0],
                outline_reviewer_model=connectors["outline_reviewer"][1],
                prose_writer_connector=connectors["prose_writer"][0],
                prose_writer_model=connectors["prose_writer"][1],
                prose_reviewer_connector=connectors["prose_reviewer"][0],
                prose_reviewer_model=connectors["prose_reviewer"][1],
                ink_scripter_connector=connectors["ink_scripter"][0],
                ink_scripter_model=connectors["ink_scripter"][1],
                ink_debugger_connector=connectors["ink_debugger"][0],
                ink_debugger_model=connectors["ink_debugger"][1],
                ink_qa_connector=connectors["ink_qa"][0],
                ink_qa_model=connectors["ink_qa"][1],
                ink_auditor_connector=connectors["ink_auditor"][0],
                ink_auditor_model=connectors["ink_auditor"][1],
                embedding_connector=self._embedding_connector,
                if_engine_connector=self._if_engine_connector,
            )

        initial_state = {
            "zworld_kvp": zworld_kvp,
            "world_slug": world_slug,
            "z_bundle_root": z_bundle_root,
            "preferences": {},
            "player_prompt": player_prompt,
            "outline": None,
            "research_notes": None,
            "experience_title": None,
            "experience_slug": None,
            "prose_draft": None,
            "ink_script": None,
            "compiled_output": None,
            "compiler_errors": [],
            "outline_feedback": None,
            "prose_feedback": None,
            "qa_feedback": None,
            "audit_feedback": None,
            "outline_review_count": 0,
            "prose_review_count": 0,
            "compile_fix_count": 0,
            "script_rewrite_count": 0,
            "status": "outlining",
            "status_message": "Starting experience generation...",
            "failure_reason": None,
            "messages": [],
        }

        log.info("start_experience_generation: calling run_process")
        result = await self.run_process(
            graph=self._experience_generation_graph,
            initial_state=initial_state,
            on_status_update=on_progress,
        )
        log.info("start_experience_generation: run_process returned status=%r", result.get("status"))

        if result.get("status") == "complete":
            compiled = result.get("compiled_output")
            exp_slug = result.get("experience_slug", "untitled")
            if compiled:
                experience = self.experience_manager.create(
                    world_slug, exp_slug, compiled
                )
                log.info(
                    "start_experience_generation: saved experience slug=%r",
                    exp_slug,
                )
                return experience
        log.warning(
            "start_experience_generation: finished with status=%r reason=%r",
            result.get("status"),
            result.get("failure_reason"),
        )
        return None

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
