"""LangGraph Ask About World graph.

Single-node agentic RAG graph per docs/Ask About World.md:

1. librarian_node — answers a user question about a Z-World by querying its
   Z-Bundle via query_world and retrieve_source tools, then produces a
   plain-text answer.

Tool calls are executed inline within the librarian node in a while loop —
no ToolNode is used (per docs/Processes.md § LangGraph tool call pattern).

Implements: src/zforge/graphs/ask_about_world_graph.py per
docs/Ask About World.md.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph

from zforge.graphs.graph_utils import extract_text_content, log_node, make_world_query_tools
from zforge.graphs.state import AskAboutWorldState

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from zforge.services.embedding.embedding_connector import EmbeddingConnector
    from zforge.services.llm.llm_connector import LlmConnector

# --- Librarian prompt (authoritative, from docs/Ask About World.md) ---

_LIBRARIAN_SYSTEM_PROMPT = """\
You are a reference librarian for a library of interactive fiction worlds. \
You will receive a JSON document describing a fictional world, e.g. title \
and brief summary. You will have access to vector and graph databases to \
provide more information. You will be asked a question about this world and \
will provide a clear and simple plain-text answer. This will typically be \
1-3 sentences, though longer responses are acceptable for complex questions."""


# --- Node Factory ---


def _make_librarian_node(
    llm_connector: LlmConnector, embedding_connector: EmbeddingConnector, allowed_node_labels: list[str],
    model_name: str | None = None,
):
    """Return an agentic RAG node that answers questions about a Z-World."""

    _model_cache: list[Any] = []

    @log_node("librarian")
    async def librarian_node(state: AskAboutWorldState) -> dict[str, Any]:
        if not _model_cache:
            _model_cache.append(llm_connector.get_model(model_name))
        model = _model_cache[0]

        z_bundle_root = state["z_bundle_root"]

        # Build retriever tools for this Z-Bundle
        query_world, retrieve_source = make_world_query_tools(
            z_bundle_root, allowed_node_labels, embedding_connector
        )

        tools = [query_world, retrieve_source]
        tool_map = {t.name: t for t in tools}
        bound_model = model.bind_tools(tools)

        # Seed messages: two system prompts + user question
        world_context = (
            "The following is a description of the fictional world about "
            "which you will answer questions.\n\n"
            + json.dumps(state["zworld_kvp"], indent=2)
        )
        # World context is placed in the HumanMessage rather than the system
        # prompt. Groq/Llama models use a chat template that embeds tool
        # definitions via <function=name> delimiters; any `<` / `>` characters
        # in the system turn (common in world JSON with arrows, HTML, etc.)
        # corrupt that template, producing malformed tool calls (tool_use_failed).
        # Keeping the system prompt to plain behavioural instructions only avoids
        # this entirely.
        messages: list[BaseMessage] = [
            SystemMessage(content=_LIBRARIAN_SYSTEM_PROMPT),
            HumanMessage(
                content=world_context + "\n\nQuestion: " + state["user_question"]
            ),
        ]

        # Tool-call loop: invoke model, process tool calls, repeat until done
        while True:
            response = await bound_model.ainvoke(messages)
            messages.append(response)

            if not (hasattr(response, "tool_calls") and response.tool_calls):
                break

            for tc in response.tool_calls:
                tool_fn = tool_map.get(tc["name"])
                if tool_fn:
                    _t0 = time.perf_counter()
                    result = await tool_fn.ainvoke(tc["args"])
                    _elapsed = time.perf_counter() - _t0
                    log.info(
                        "librarian_node: tool %s returned %d chars in %.2fs",
                        tc["name"],
                        len(str(result)),
                        _elapsed,
                    )
                    messages.append(
                        ToolMessage(
                            content=str(result),
                            tool_call_id=tc["id"],
                            name=tc["name"],
                        )
                    )

        answer = extract_text_content(getattr(response, "content", ""))
        return {"answer": answer, "messages": messages}

    return librarian_node


# --- Graph Builder ---


def build_ask_about_world_graph(
    llm_connector: LlmConnector,
    embedding_connector: EmbeddingConnector,
    allowed_node_labels: list[str],
    model_name: str | None = None,
):
    """Build and compile the Ask About World LangGraph StateGraph.

    Parameters
    ----------
    llm_connector:
        LLM connector for the Librarian node.
    embedding_connector:
        Embedding connector for the retrieval tools.
    allowed_node_labels:
        PascalCase node type names for graph queries.
    model_name:
        Optional model name override.
    """
    graph = StateGraph(AskAboutWorldState)

    graph.add_node(
        "librarian",
        _make_librarian_node(
            llm_connector, embedding_connector, allowed_node_labels, model_name
        ),
    )

    graph.set_entry_point("librarian")
    graph.add_edge("librarian", END)

    return graph.compile()


# --- Entry Point ---


async def run_ask_about_world(
    z_bundle_root: str,
    zworld_kvp: dict[str, Any],
    user_question: str,
    llm_connector: LlmConnector,
    embedding_connector: EmbeddingConnector,
    allowed_node_labels: list[str],
    model_name: str | None = None,
) -> str:
    """Build the Ask About World graph, invoke it, and return the answer.

    Parameters
    ----------
    z_bundle_root:
        Filesystem path to the Z-Bundle root directory.
    zworld_kvp:
        Full KVP JSON dict for the Z-World.
    user_question:
        Raw user question text.
    llm_connector:
        LLM connector for the Librarian node.
    embedding_connector:
        Embedding connector for the retrieval tools.
    allowed_node_labels:
        PascalCase node type names for graph queries.
    model_name:
        Optional model name override.

    Returns
    -------
    str
        Plain-text answer string.
    """
    graph = build_ask_about_world_graph(
        llm_connector=llm_connector,
        embedding_connector=embedding_connector,
        allowed_node_labels=allowed_node_labels,
        model_name=model_name,
    )

    initial_state: AskAboutWorldState = {
        "z_bundle_root": z_bundle_root,
        "zworld_kvp": zworld_kvp,
        "user_question": user_question,
        "answer": "",
        "messages": [],
    }

    result = await graph.ainvoke(initial_state)
    return result.get("answer", "")
