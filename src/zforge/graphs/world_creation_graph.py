"""LangGraph world creation graph.

Factory function builds a StateGraph(CreateWorldState) with editor and
designer agent nodes, ToolNode, and conditional routing.

Implements: src/zforge/graphs/world_creation_graph.py per
docs/World Generation.md and docs/LLM Orchestration.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from zforge.graphs.state import CreateWorldState
from zforge.tools.world_tools import (
    all_world_tools,
    world_create_zworld,
    world_explain_rejection,
    world_validate_input,
    MAX_VALIDATION_ATTEMPTS,
)

if TYPE_CHECKING:
    from zforge.services.llm.llm_connector import LlmConnector


# --- System Prompts ---

_EDITOR_SYSTEM_PROMPT = (
    "You are a literature editor. You are to determine whether the "
    "following is a clear description of a fictional world, listing "
    "characters and their relationships with one another, locations, "
    "and events."
)

_DESIGNER_SYSTEM_PROMPT_TEMPLATE = """\
You are a designer for an interactive fiction system. ZWorlds, used as the \
basis of your interactive fiction experiences, consist of the following:

A ZWorld specification includes:
- id: a unique text identifier (e.g., "discworld")
- name: the display name (e.g., "Discworld")
- locations: nested list of locations, each with id, name, description, and optional sublocations
- characters: each with id, one or more names (with optional context), and history
- relationships: describing the personal history and current relationship between two characters (by id)
- events: significant occurrences with descriptions and dates (literal or relative)

Create a ZWorld from the following description of a fictional world:

{input_text}"""

_REJECTION_SYSTEM_PROMPT = (
    "The input text was evaluated as inadequate for world creation. "
    "Please explain clearly why the text is inadequate or inappropriate "
    "as a fictional world description."
)


# --- Node Factories ---


def _make_editor_node(llm_connector: LlmConnector):
    model = llm_connector.get_model()

    def editor_node(state: CreateWorldState) -> dict:
        status = state["status"]

        if status == "awaiting_rejection_explanation":
            system = _REJECTION_SYSTEM_PROMPT
            action = (
                "Explain why the following text is inadequate as a world "
                f"description:\n\n{state['input_text']}"
            )
            tools = [world_explain_rejection]
        else:
            system = _EDITOR_SYSTEM_PROMPT
            action = (
                "Evaluate the following world description:\n\n"
                f"{state['input_text']}"
            )
            tools = [world_validate_input]

        response = model.bind_tools(tools).invoke([
            SystemMessage(content=system),
            HumanMessage(content=action),
        ])
        return {"messages": [response]}

    return editor_node


def _make_designer_node(llm_connector: LlmConnector):
    model = llm_connector.get_model()

    def designer_node(state: CreateWorldState) -> dict:
        system = _DESIGNER_SYSTEM_PROMPT_TEMPLATE.format(
            input_text=state["input_text"]
        )
        response = model.bind_tools([world_create_zworld]).invoke([
            SystemMessage(content=system),
            HumanMessage(content="Build the specified ZWorld."),
        ])
        return {"messages": [response]}

    return designer_node


# --- Routing ---


def _route_after_tool(state: CreateWorldState) -> str:
    status = state["status"]
    validation_count = state.get("validation_iterations", 0)

    if status == "awaiting_validation":
        if validation_count >= MAX_VALIDATION_ATTEMPTS:
            return "explain"
        return "editor"
    elif status == "awaiting_generation":
        return "designer"
    elif status == "awaiting_rejection_explanation":
        return "explain"
    elif status in ("complete", "failed"):
        return "end"
    return "end"


def _route_explain(state: CreateWorldState) -> str:
    """Route from explain: always go to tools for the explain_rejection call."""
    return "tools"


# --- Graph Builder ---


def build_create_world_graph(llm_connector: LlmConnector):
    """Build and compile the world creation LangGraph StateGraph."""
    graph = StateGraph(CreateWorldState)

    graph.add_node("editor", _make_editor_node(llm_connector))
    graph.add_node("designer", _make_designer_node(llm_connector))
    graph.add_node("tools", ToolNode(all_world_tools))

    graph.set_entry_point("editor")
    graph.add_edge("editor", "tools")
    graph.add_edge("designer", "tools")
    graph.add_conditional_edges("tools", _route_after_tool, {
        "editor": "editor",
        "designer": "designer",
        "explain": "editor",
        "end": END,
    })

    return graph.compile()
