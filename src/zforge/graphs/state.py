"""LangGraph state TypedDicts for Z-Forge processes.

ExperienceGenerationState per docs/Experience Generation.md.
CreateWorldState per docs/World Generation.md.
DocumentParsingState per docs/Parsing Documents to Z-Bundles.md.

Uses Annotated[int, operator.add] for iteration counters and
Annotated[list, add_messages] for LangGraph message history.

Implements: src/zforge/graphs/state.py per docs/LLM Orchestration.md.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class ExperienceGenerationState(TypedDict):
    """State for the experience generation LangGraph graph."""

    # Inputs (set at initialization)
    z_world: dict[str, Any]
    preferences: dict[str, Any]
    player_prompt: str | None

    # Artifacts (set by @tool functions during execution)
    outline: str | None
    tech_notes: str | None
    outline_notes: str | None
    script: str | None
    script_notes: str | None
    tech_edit_report: str | None
    story_edit_report: str | None
    compiled_output: bytes | None
    compiler_errors: list[str]

    # Iteration counters — use operator.add reducer so tools return 1 to increment
    outline_iterations: Annotated[int, operator.add]
    script_compile_iterations: Annotated[int, operator.add]
    author_review_iterations: Annotated[int, operator.add]
    tech_edit_iterations: Annotated[int, operator.add]
    story_edit_iterations: Annotated[int, operator.add]

    # Status
    status: str
    status_message: str
    failure_reason: str | None
    current_rationale: str | None
    action_log: Annotated[list, operator.add]

    # LangGraph message history — must use add_messages reducer
    messages: Annotated[list, add_messages]


class DocumentParsingState(TypedDict):
    """State for the document parsing LangGraph sub-graph.

    Per docs/Parsing Documents to Z-Bundles.md § Implementation.
    """

    input_text: str
    z_bundle_root: str
    allowed_nodes: list[str]
    allowed_relationships: list[str]
    chunks: list[str]
    documents: list
    current_chunk_index: Annotated[int, operator.add]
    status: str
    status_message: str


class CreateWorldState(TypedDict):
    """State for the world creation LangGraph graph.

    Per docs/World Generation.md § Implementation.
    """

    input_text: str
    z_bundle_root: str | None
    zworld_kvp: dict | None
    status: str
    status_message: str
    failure_reason: str | None
    messages: Annotated[list, add_messages]
