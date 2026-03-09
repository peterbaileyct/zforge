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

import asyncio
import json
import logging
import os
import re
import uuid as uuid_mod
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph

from zforge.graphs.graph_utils import extract_text_content, log_node
from zforge.graphs.state import CreateWorldState
from zforge.graphs.document_parsing_graph import _LLAMA_EXECUTOR

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from zforge.managers.zworld_manager import ZWorldManager
    from zforge.services.embedding.embedding_connector import EmbeddingConnector
    from zforge.services.llm.llm_connector import LlmConnector

# --- World Generation entity schema (from docs/World Generation.md Step 1) ---

ALLOWED_NODES = [
    "Character", "Location", "Event", "Faction", "Artifact", "Era",
    "Culture", "Deity", "Prophecy", "Concept", "Mechanic", "Trope",
    "Species", "Occupation",
]

ALLOWED_RELATIONSHIPS = [
    "friends_with", "enemy_of", "parent_of", "mentor_of", "present_at",
    "born_in", "member_of", "leads", "is_a", "owns", "seeks",
    "subject_to", "embodies", "west_of", "inside_of", "controls",
    "native_to", "located_at", "occurred_at", "allied_with",
    "at_war_with", "caused", "preceded",
]

# --- Summarizer prompt (authoritative, from docs/World Generation.md Step 2) ---

_SUMMARIZER_SYSTEM_PROMPT = """\
You are a junior script editor with access to a hybrid data store describing \
a fictional world. Look up appropriate details to produce the following \
information about the world in a JSON document:
- `title`: the full display name of the world (e.g. "Discworld")
- `summary`: 3–5 sentences describing the world in diegetic terms, suitable \
for helping a player understand the world at a glance
- `setting_era`: a brief label for when the world is nominally set (e.g. \
"pre-industrial fantasy", "far future", "alternate 1920s")
- `source_canon`: a list of source work titles — books, films, games — the \
world is drawn from
- `content_advisories`: a list of thematic flags relevant to experience \
generation (e.g. "moderate violence", "political intrigue", "body horror")

Use the retriever tools to look up information before producing your final \
answer. When you are ready, respond with ONLY a JSON object (no markdown \
fencing) with exactly these keys: title, summary, setting_era, source_canon, \
content_advisories."""


# --- Node Factories ---


def _make_document_parsing_node(
    contextualizer_connector,
    graph_extractor_connector,
    embedding_connector,
    config,
    bundles_root: str,
    contextualizer_model: str | None = None,
    graph_extractor_model: str | None = None,
):
    """Return a node that runs the document parsing sub-graph."""

    from zforge.graphs.document_parsing_graph import build_document_parsing_graph

    parsing_graph = build_document_parsing_graph(
        contextualizer_connector=contextualizer_connector,
        graph_extractor_connector=graph_extractor_connector,
        embedding_connector=embedding_connector,
        config=config,
        contextualizer_model=contextualizer_model,
        graph_extractor_model=graph_extractor_model,
    )

    @log_node("document_parsing")
    async def document_parsing_node(state: CreateWorldState) -> dict:
        # Derive a temporary slug from first ~50 chars of input
        title_hint = state["input_text"][:50].strip().split("\n")[0]
        temp_slug = re.sub(r"[^a-z0-9]+", "-", title_hint.lower()).strip("-") or "world"
        z_bundle_root = os.path.join(bundles_root, "world", temp_slug)

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

        # Run the parsing sub-graph asynchronously
        result = await parsing_graph.ainvoke(parsing_state)

        log.info(
            "document_parsing_node: sub-graph completed — status=%r",
            result.get("status"),
        )

        return {
            "z_bundle_root": z_bundle_root,
            "status": "summarizing",
            "status_message": "Document parsing complete; summarizing...",
        }

    return document_parsing_node


def _make_summarizer_node(
    llm_connector, embedding_connector, model_name: str | None = None
):
    """Return an agentic RAG node that queries the Z-Bundle to produce KVP JSON."""

    _model_cache: list = []

    @log_node("summarizer")
    async def summarizer_node(state: CreateWorldState) -> dict:
        if not _model_cache:
            _model_cache.append(llm_connector.get_model(model_name))
        model = _model_cache[0]

        z_bundle_root = state["z_bundle_root"]

        # Build retriever tools for this Z-Bundle
        @tool
        async def retrieve_vector(query: str) -> str:
            """Search the Z-Bundle's vector store for semantically similar chunks.

            Args:
                query: Natural language search query.
            """
            import lancedb

            vector_path = f"{z_bundle_root}/vector"
            loop = asyncio.get_running_loop()
            embedder = embedding_connector.get_embeddings()
            query_vec = await loop.run_in_executor(
                _LLAMA_EXECUTOR,
                lambda: embedder.embed_query(query),
            )
            db = await lancedb.connect_async(vector_path)
            table = await db.open_table("chunks")
            results_arrow = await (
                await table.search(query_vec, query_type="vector")
            ).limit(5).to_arrow()
            texts = results_arrow.column("text").to_pylist()
            if not texts:
                return "No results found."
            return "\n\n---\n\n".join(t for t in texts if t)

        @tool
        def retrieve_graph(query: str) -> str:
            """Query the Z-Bundle's property graph for structured entity data.

            Args:
                query: A Cypher-style query or entity name to look up.
            """
            import kuzu
            from langchain_community.graphs import KuzuGraph

            graph_path = f"{z_bundle_root}/propertygraph"
            db = kuzu.Database(graph_path)
            graph = KuzuGraph(db, allow_dangerous_requests=True)
            schema = graph.get_schema
            return f"Graph schema:\n{schema}\n\nUse retrieve_vector for detailed content."

        tools = [retrieve_vector, retrieve_graph]
        messages = list(state.get("messages") or [])

        # If this is the first invocation, seed with the system/human messages
        if not messages:
            messages = [
                SystemMessage(content=_SUMMARIZER_SYSTEM_PROMPT),
                HumanMessage(
                    content="Produce the JSON metadata for this world. "
                    "Use the retriever tools to look up details first."
                ),
            ]

        bound_model = model.bind_tools(tools)
        response = await bound_model.ainvoke(messages)
        messages.append(response)

        # Process tool calls inline (per Processes.md — no ToolNode)
        state_updates: dict = {"messages": messages}

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


def _parse_summarizer_json(content: str) -> dict | None:
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


def _make_finalizer_node(zworld_manager):
    """Return a deterministic node that constructs ZWorld and writes the Z-Bundle."""

    @log_node("finalizer")
    def finalizer_node(state: CreateWorldState) -> dict:
        from zforge.models.zworld import ZWorld

        kvp = state.get("zworld_kvp")
        if not kvp:
            log.error("finalizer_node: no zworld_kvp in state")
            return {
                "status": "failed",
                "failure_reason": "Summarizer produced no metadata",
                "status_message": "World creation failed: no metadata extracted",
            }

        title = kvp.get("title", "Unknown World")
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")

        zworld = ZWorld(
            title=title,
            slug=slug,
            uuid=str(uuid_mod.uuid4()),
            summary=kvp.get("summary", ""),
            setting_era=kvp.get("setting_era", ""),
            source_canon=kvp.get("source_canon", []),
            content_advisories=kvp.get("content_advisories", []),
        )

        if zworld_manager is not None:
            # Rename Z-Bundle directory from temp slug to final slug
            old_root = state.get("z_bundle_root", "")
            new_root = os.path.join(os.path.dirname(old_root), slug) if old_root else ""
            if old_root and new_root and old_root != new_root and os.path.exists(old_root):
                os.rename(old_root, new_root)

            zworld_manager.create(zworld, raw_text=state["input_text"])
        else:
            log.error(
                "finalizer_node: ZWorldManager not provided — Z-Bundle not written"
            )

        return {
            "z_bundle_root": new_root if old_root != new_root else old_root,
            "status": "complete",
            "status_message": f"World '{title}' created successfully",
        }

    return finalizer_node


# --- Routing ---


def _route_after_summarizer(state: CreateWorldState) -> str:
    """Loop back to summarizer if tool calls are pending, else finalize."""
    status = state.get("status", "")
    if status == "finalizing":
        return "finalizer"
    if status == "failed":
        return "end"
    # Still summarizing (tool calls were made) — loop back
    return "summarizer"


# --- Graph Builder ---


def build_create_world_graph(
    summarizer_connector: LlmConnector,
    contextualizer_connector: LlmConnector,
    graph_extractor_connector: LlmConnector,
    embedding_connector: EmbeddingConnector,
    zworld_manager: ZWorldManager,
    config,
    bundles_root: str,
    summarizer_model: str | None = None,
    contextualizer_model: str | None = None,
    graph_extractor_model: str | None = None,
):
    """Build and compile the world creation LangGraph StateGraph.

    Parameters
    ----------
    summarizer_connector:
        LLM connector for the Step 2 summarizer (agentic RAG).
    contextualizer_connector / graph_extractor_connector:
        LLM connectors for the document_parsing sub-graph.
    embedding_connector:
        Embedding connector for vector ingestion and retriever tools.
    zworld_manager:
        ZWorldManager instance for writing the final Z-Bundle.
    config:
        ZForgeConfig providing parsing_chunk_size and parsing_chunk_overlap.
    bundles_root:
        Root directory for Z-Bundles (e.g. "bundles/").
    summarizer_model / contextualizer_model / graph_extractor_model:
        Optional model name overrides.
    """
    graph = StateGraph(CreateWorldState)

    graph.add_node(
        "document_parsing",
        _make_document_parsing_node(
            contextualizer_connector=contextualizer_connector,
            graph_extractor_connector=graph_extractor_connector,
            embedding_connector=embedding_connector,
            config=config,
            bundles_root=bundles_root,
            contextualizer_model=contextualizer_model,
            graph_extractor_model=graph_extractor_model,
        ),
    )
    graph.add_node(
        "summarizer",
        _make_summarizer_node(
            summarizer_connector, embedding_connector, summarizer_model
        ),
    )
    graph.add_node("finalizer", _make_finalizer_node(zworld_manager))

    graph.set_entry_point("document_parsing")
    graph.add_edge("document_parsing", "summarizer")
    graph.add_conditional_edges(
        "summarizer",
        _route_after_summarizer,
        {
            "summarizer": "summarizer",
            "finalizer": "finalizer",
            "end": END,
        },
    )
    graph.add_edge("finalizer", END)

    return graph.compile()

