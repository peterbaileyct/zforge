"""LangGraph world creation graph.

Three-node pipeline per docs/World Generation.md:

1. document_parsing_node — invokes the document_parsing_graph as a sub-graph
   to populate the Z-Bundle's vector store and property graph.
2. summarizer_node — agentic RAG that queries the populated Z-Bundle via
   retriever tools to produce KVP metadata JSON.
3. finalizer_node — deterministic construction of ZWorld + ZWorldManager.create().

Tool calls are executed inline within the summarizer node — no ToolNode is used
(per docs/Processes.md § LangGraph tool call pattern).

Implements: src/zforge/graphs/world_creation_graph.py per
docs/World Generation.md.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import uuid as uuid_mod
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph

from zforge.graphs.graph_utils import (
    ALLOWED_NODES,
    ALLOWED_RELATIONSHIPS,
    extract_text_content,
    log_node,
    make_world_query_tools,
)
from zforge.graphs.state import CreateWorldState

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from zforge.managers.zworld_manager import ZWorldManager
    from zforge.models.zforge_config import ZForgeConfig
    from zforge.services.embedding.embedding_connector import EmbeddingConnector
    from zforge.services.llm.llm_connector import LlmConnector

# --- World Generation entity schema (from docs/World Generation.md Step 1) ---
# Canonical definitions live in graph_utils.ALLOWED_NODES / ALLOWED_RELATIONSHIPS
# (per docs/Z-World.md § allowed_nodes).

# --- Summarizer prompt (authoritative, from docs/World Generation.md Step 2) ---

_SUMMARIZER_SYSTEM_PROMPT = """\
You are a junior script editor with access to a hybrid data store describing \
a fictional world. Look up appropriate details to produce the following \
information about the world in a JSON document:
- `title`: the full display name of the world (e.g. "The Dragonet Prophecy")
- `summary`: 3–5 sentences describing the world in diegetic terms, suitable \
for helping a player understand the world at a glance
- `setting_era`: a brief label for when the world is nominally set (e.g. \
"pre-industrial fantasy", "far future", "alternate 1920s")
- `source_canon`: a list of source work titles — books, films, games — the \
world is drawn from
- `content_advisories`: a list of thematic flags relevant to experience \
generation (e.g. "moderate violence", "political intrigue", "body horror")

Use the retriever tools to look up information before producing your final \
answer. DO NOT use information from these examples in your final output. \
ONLY use data retrieved via your tools. When you are ready, respond with \
ONLY a JSON object (no markdown fencing) with exactly these keys: title, \
summary, setting_era, source_canon, content_advisories."""


# --- Node Factories ---


def _make_document_parsing_node(
    graph_extractor_connector: LlmConnector,
    entity_summarizer_connector: LlmConnector,
    embedding_connector: EmbeddingConnector,
    config: ZForgeConfig,
    bundles_root: str,
    graph_extractor_model: str | None = None,
    entity_summarizer_model: str | None = None,
):
    """Return a node that runs the document parsing sub-graph."""

    from zforge.graphs.document_parsing_graph import build_document_parsing_graph

    parsing_graph = build_document_parsing_graph(
        graph_extractor_connector=graph_extractor_connector,
        entity_summarizer_connector=entity_summarizer_connector,
        embedding_connector=embedding_connector,
        config=config,
        graph_extractor_model=graph_extractor_model,
        entity_summarizer_model=entity_summarizer_model,
    )

    @log_node("document_parsing")
    async def document_parsing_node(state: CreateWorldState) -> dict[str, Any]:
        # If resuming after duplicate confirmation, parsing is already done — skip.
        if state.get("z_bundle_root"):
            log.info("document_parsing_node: z_bundle_root already set — skipping")
            return {}

        # Generate (or reuse) a stable UUID for this world's in-progress bundle.
        world_uuid = state.get("world_uuid") or str(uuid_mod.uuid4())
        z_bundle_root = os.path.join(bundles_root, "worlds-in-progress", world_uuid)

        parsing_state = {
            "input_text": state["input_text"],
            "z_bundle_root": z_bundle_root,
            "allowed_nodes": ALLOWED_NODES,
            "allowed_relationships": ALLOWED_RELATIONSHIPS,
            "chunks": [],
            "documents": [],
            "current_chunk_index": 0,
            "status": "starting",
            "status_message": "Starting document parsing...",
        }

        # Stream the parsing sub-graph so every node update is visible in the
        # console log (rather than blocking silently until ainvoke returns).
        result = parsing_state.copy()
        async for event in parsing_graph.astream(
            parsing_state, stream_mode="updates"
        ):
            for node_name, node_output in event.items():
                if isinstance(node_output, dict):
                    result = {**result, **node_output}
                    sub_msg = node_output.get("status_message")
                    log.info(
                        "document_parsing_node: [sub] node=%r status=%r message=%r",
                        node_name,
                        node_output.get("status"),
                        sub_msg,
                    )

        log.info(
            "document_parsing_node: sub-graph completed — status=%r",
            result.get("status"),
        )

        return {
            "world_uuid": world_uuid,
            "z_bundle_root": z_bundle_root,
            "status": "summarizing",
            "status_message": "Document parsing complete; summarizing...",
        }

    return document_parsing_node


def _make_summarizer_node(
    llm_connector: LlmConnector, embedding_connector: EmbeddingConnector, model_name: str | None = None
):
    """Return an agentic RAG node that queries the Z-Bundle to produce KVP JSON."""

    _model_cache: list[Any] = []

    @log_node("summarizer")
    async def summarizer_node(state: CreateWorldState) -> dict[str, Any]:
        # If resuming after duplicate confirmation, metadata is already set — skip.
        if state.get("zworld_kvp"):
            log.info("summarizer_node: zworld_kvp already set — skipping")
            return {
                "status": "finalizing",
                "status_message": "Resuming with existing metadata...",
            }

        if not _model_cache:
            _model_cache.append(llm_connector.get_model(model_name))
        model = _model_cache[0]

        z_bundle_root = state.get("z_bundle_root") or ""

        # Build retriever tools for this Z-Bundle
        (
            query_entities, retrieve_source, _find_rel, _find_rel_name,
            _list_ent, _get_nb, _find_p, _get_src,
        ) = make_world_query_tools(
            z_bundle_root, ALLOWED_NODES, embedding_connector
        )

        tools = [query_entities, retrieve_source]
        messages: list[BaseMessage] = list(state.get("messages") or [])

        # If this is the first invocation, seed with the system/human messages
        if not messages:
            messages = [
                SystemMessage(content=_SUMMARIZER_SYSTEM_PROMPT),
                HumanMessage(
                    content=(
                        "Process the world described in the hybrid data store. "
                        "First, identify the title and source material. Then, "
                        "search for a diegetic summary and thematic advisories. "
                        "Finally, produce the JSON metadata object. Only use "
                        "information retrieved via tools; do not hallucinate."
                    )
                ),
            ]

        bound_model = model.bind_tools(tools)
        response = await bound_model.ainvoke(messages)
        messages.append(response)

        # Process tool calls inline (per Processes.md — no ToolNode)
        state_updates: dict[str, Any] = {"messages": messages}

        if hasattr(response, "tool_calls") and response.tool_calls:
            tool_map = {t.name: t for t in tools}
            for tc in response.tool_calls:
                tool_fn = tool_map.get(tc["name"])
                if tool_fn:
                    result = await tool_fn.ainvoke(tc["args"])
                    log.info(
                        "summarizer_node: tool %s returned %d chars",
                        tc["name"],
                        len(str(result)),
                    )
                    messages.append(
                        ToolMessage(
                            content=str(result),
                            tool_call_id=tc["id"],
                            name=tc["name"],
                        )
                    )
            state_updates["messages"] = messages
            state_updates["status"] = "summarizing"
            state_updates["status_message"] = (
                f"Summarizer called {len(response.tool_calls)} tool(s); continuing..."
            )
        else:
            # No tool calls — LLM has produced its final answer
            content = extract_text_content(getattr(response, "content", ""))
            kvp = _parse_summarizer_json(content)
            if kvp:
                state_updates["zworld_kvp"] = kvp
                state_updates["status"] = "finalizing"
                state_updates["status_message"] = (
                    f"Summarizer produced metadata for '{kvp.get('title', '?')}'"
                )
            else:
                log.warning(
                    "summarizer_node: could not parse JSON from response — "
                    "marking failed. Preview: %r",
                    content[:300],
                )
                state_updates["status"] = "failed"
                state_updates["failure_reason"] = (
                    "Summarizer did not produce valid JSON"
                )
                state_updates["status_message"] = (
                    "World creation failed: summarizer output was not valid JSON"
                )

        return state_updates

    return summarizer_node


def _parse_summarizer_json(content: str) -> dict[str, Any] | None:
    """Extract a JSON object from the summarizer's response text."""
    # Try direct parse
    try:
        return json.loads(content.strip())
    except json.JSONDecodeError:
        pass

    # Try stripping markdown fencing
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding first { to last }
    brace_start = content.find("{")
    brace_end = content.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        try:
            return json.loads(content[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            pass

    return None


def _make_duplicate_check_node(zworld_manager: ZWorldManager | None):
    """Return a node that checks for an existing world with a matching title."""

    @log_node("duplicate_check")
    def duplicate_check_node(state: CreateWorldState) -> dict[str, Any]:
        # If the user has already made a decision (resuming), act on it.
        overwrite_decision = state.get("overwrite_decision")
        if overwrite_decision == "cancel":
            return {
                "status": "cancelled",
                "status_message": "World creation cancelled by user.",
            }
        if overwrite_decision == "overwrite":
            return {
                "status": "finalizing",
                "status_message": "Overwriting existing world...",
            }

        # No decision yet — check for a title collision.
        kvp = state.get("zworld_kvp") or {}
        title = kvp.get("title", "")
        title_slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")

        if zworld_manager is not None and title_slug:
            for w in zworld_manager.list_all():
                existing_slug = re.sub(r"[^a-z0-9]+", "-", w.title.lower()).strip("-")
                if existing_slug == title_slug:
                    log.info(
                        "duplicate_check_node: collision — new title %r matches existing %r (%r)",
                        title,
                        w.title,
                        w.slug,
                    )
                    return {
                        "status": "awaiting_confirmation",
                        "conflicting_slug": w.slug,
                        "status_message": (
                            f"A world named '{w.title}' already exists. "
                            "Please confirm whether to overwrite."
                        ),
                    }

        # No conflict — proceed straight to finalisation.
        return {
            "status": "finalizing",
            "status_message": "No duplicate found; finalizing...",
        }

    return duplicate_check_node


def _make_finalizer_node(zworld_manager: ZWorldManager | None):
    """Return a deterministic node that constructs ZWorld and writes the Z-Bundle."""

    @log_node("finalizer")
    def finalizer_node(state: CreateWorldState) -> dict[str, Any]:
        from zforge.models.zworld import ZWorld

        kvp = state.get("zworld_kvp")
        if not kvp:
            log.error("finalizer_node: no zworld_kvp in state")
            return {
                "status": "failed",
                "failure_reason": "Summarizer produced no metadata",
                "status_message": "World creation failed: no metadata extracted",
            }

        title: str = kvp.get("title", "Unknown World") or "Unknown World"
        slug: str = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")

        # Honour locked overrides (used by reindex_world)
        if state.get("locked_title"):
            title = state["locked_title"] or title
        if state.get("locked_slug"):
            slug = state["locked_slug"] or slug

        # Use the UUID that was assigned at the very start of the pipeline.
        world_uuid = state.get("world_uuid") or str(uuid_mod.uuid4())

        zworld = ZWorld(
            title=title,
            slug=slug,
            uuid=world_uuid,
            summary=kvp.get("summary", ""),
            setting_era=kvp.get("setting_era", ""),
            source_canon=kvp.get("source_canon", []),
            content_advisories=kvp.get("content_advisories", []),
        )

        if zworld_manager is not None:
            # Move the in-progress bundle to its final location.
            old_root = state.get("z_bundle_root", "")
            new_root = str(zworld_manager._world_root(slug))  # pyright: ignore[reportPrivateUsage]

            # If overwriting, remove the old world first.
            conflicting_slug = state.get("conflicting_slug")
            if state.get("overwrite_decision") == "overwrite" and conflicting_slug:
                existing_path = zworld_manager._world_root(conflicting_slug)  # pyright: ignore[reportPrivateUsage]
                if existing_path.exists():
                    shutil.rmtree(existing_path)
                    log.info(
                        "finalizer_node: deleted existing world at %s", existing_path
                    )

            if old_root and os.path.exists(old_root):
                os.makedirs(os.path.dirname(new_root), exist_ok=True)
                os.rename(old_root, new_root)
                log.info(
                    "finalizer_node: moved bundle %s → %s", old_root, new_root
                )

            zworld_manager.create(zworld, raw_text=state["input_text"])
        else:
            log.error(
                "finalizer_node: ZWorldManager not provided — Z-Bundle not written"
            )
            new_root = ""

        return {
            "z_bundle_root": new_root,
            "status": "complete",
            "status_message": f"World '{title}' created successfully",
        }

    return finalizer_node


# --- Routing ---


def _route_after_summarizer(state: CreateWorldState) -> str:
    """Loop back to summarizer if tool calls are pending, else run duplicate check."""
    status = state.get("status", "")
    if status == "finalizing":
        return "duplicate_check"
    if status == "failed":
        return "end"
    # Still summarizing (tool calls were made) — loop back
    return "summarizer"


def _route_after_duplicate_check(state: CreateWorldState) -> str:
    """Route to finalizer if clear to proceed, otherwise end (await user or cancel)."""
    status = state.get("status", "")
    if status == "finalizing":
        return "finalizer"
    # "awaiting_confirmation", "cancelled", "failed" all exit the graph.
    return "end"


# --- Graph Builder ---


def build_create_world_graph(
    summarizer_connector: LlmConnector,
    graph_extractor_connector: LlmConnector,
    entity_summarizer_connector: LlmConnector,
    embedding_connector: EmbeddingConnector,
    zworld_manager: ZWorldManager,
    config: ZForgeConfig,
    bundles_root: str,
    summarizer_model: str | None = None,
    graph_extractor_model: str | None = None,
    entity_summarizer_model: str | None = None,
):
    """Build and compile the world creation LangGraph StateGraph.

    Parameters
    ----------
    summarizer_connector:
        LLM connector for the Step 2 summarizer (agentic RAG).
    graph_extractor_connector / entity_summarizer_connector:
        LLM connectors for the document_parsing sub-graph.
    embedding_connector:
        Embedding connector for vector ingestion and retriever tools.
    zworld_manager:
        ZWorldManager instance for writing the final Z-Bundle.
    config:
        ZForgeConfig providing parsing/chunking/dedup/entity config fields.
    bundles_root:
        Root directory for Z-Bundles (e.g. "bundles/").
    summarizer_model / graph_extractor_model / entity_summarizer_model:
        Optional model name overrides.
    """
    graph = StateGraph(CreateWorldState)

    graph.add_node(
        "document_parsing",
        _make_document_parsing_node(
            graph_extractor_connector=graph_extractor_connector,
            entity_summarizer_connector=entity_summarizer_connector,
            embedding_connector=embedding_connector,
            config=config,
            bundles_root=bundles_root,
            graph_extractor_model=graph_extractor_model,
            entity_summarizer_model=entity_summarizer_model,
        ),
    )
    graph.add_node(
        "summarizer",
        _make_summarizer_node(
            summarizer_connector, embedding_connector, summarizer_model
        ),
    )
    graph.add_node(
        "duplicate_check", _make_duplicate_check_node(zworld_manager)
    )
    graph.add_node("finalizer", _make_finalizer_node(zworld_manager))

    graph.set_entry_point("document_parsing")
    graph.add_edge("document_parsing", "summarizer")
    graph.add_conditional_edges(
        "summarizer",
        _route_after_summarizer,
        {
            "summarizer": "summarizer",
            "duplicate_check": "duplicate_check",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "duplicate_check",
        _route_after_duplicate_check,
        {
            "finalizer": "finalizer",
            "end": END,
        },
    )
    graph.add_edge("finalizer", END)

    return graph.compile()

