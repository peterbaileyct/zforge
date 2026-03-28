"""LangGraph state TypedDicts for Z-Forge processes.

ExperienceGenerationState per docs/Experience Generation.md.
CreateWorldState per docs/World Generation.md.
DocumentParsingState per docs/Parsing Documents to Z-Bundles.md.
AskAboutWorldState per docs/Ask About World.md.

Uses Annotated[int, operator.add] for iteration counters and
Annotated[list, add_messages] for LangGraph message history.

Implements: src/zforge/graphs/state.py per docs/LLM Orchestration.md.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ExperienceGenerationState(TypedDict):
    """State for the experience generation LangGraph graph.

    Per docs/Experience Generation.md § Implementation.
    """

    # Inputs (set at initialization)
    zworld_kvp: dict[str, Any] | None
    world_slug: str | None
    z_bundle_root: str | None
    preferences: dict[str, Any]
    player_prompt: str

    # Artifacts (set by agent nodes during execution)
    outline: str | None
    research_notes: str | None
    research_request: str | None
    research_caller: str | None
    experience_title: str | None
    experience_slug: str | None
    prose_draft: str | None
    ink_script: str | None
    compiled_output: bytes | None
    compiler_errors: list[str]

    # Feedback (set by reviewers, consumed by writers)
    outline_feedback: str | None
    prose_feedback: str | None
    qa_feedback: str | None
    audit_feedback: str | None

    # Debugger handoff — used when routing non-Ink content through ink_debugger
    debugger_mode: str | None        # "ink" or "json"; drives ink_debugger dispatch
    debugger_return_node: str | None # node to route to after debugger completes
    debugger_input: str | None       # raw content to repair in JSON mode

    # Arbiter inputs (set by reviewer when Story Editor rejects; cleared by arbiter)
    story_editor_feedback: str | None   # Raw Story Editor rejection reason
    tech_editor_feedback: str | None    # Raw Tech Editor rejection reason when TE also failed

    # Iteration counters — use operator.add reducer so nodes return 1 to increment
    outline_review_count: Annotated[int, operator.add]
    prose_review_count: Annotated[int, operator.add]
    compile_fix_count: Annotated[int, operator.add]
    script_rewrite_count: Annotated[int, operator.add]
    research_call_count: Annotated[int, operator.add]  # shared across all research-capable nodes

    # Status
    status: str
    status_message: str
    failure_reason: str | None

    # Observability — set per-node, replaced (not accumulated) on each update
    last_step_rationale: str | None     # 1-2 sentence decision summary from reviewer/QA/auditor nodes
    action_log: list[dict[str, Any]]    # Tool call and event records emitted by agentic nodes

    # LangGraph message history — for observability
    messages: Annotated[list[BaseMessage], add_messages]


class DocumentParsingState(TypedDict):
    """State for the document parsing LangGraph sub-graph.

    Per docs/Parsing Documents to Z-Bundles.md § Implementation.
    """

    input_text: str
    z_bundle_root: str
    allowed_nodes: list[str]
    allowed_relationships: list[str]
    chunks: list[str]
    context_chunks: list[str]
    retrieval_documents: list[Any]  # list of Document objects with metadata
    current_chunk_index: Annotated[int, operator.add]
    status: str
    status_message: str


class CreateWorldState(TypedDict):
    """State for the world creation LangGraph graph.

    Per docs/World Generation.md § Implementation.
    """

    input_text: str
    world_uuid: str | None          # Pre-assigned at graph entry; stable across resume
    z_bundle_root: str | None       # worlds-in-progress/{uuid}/ until finalised
    zworld_kvp: dict[str, Any] | None
    conflicting_slug: str | None    # Set by duplicate_check if a same-title world exists
    overwrite_decision: str | None  # "overwrite" | "cancel" | None
    locked_slug: str | None         # If set, Finalizer uses this instead of deriving (reindex)
    locked_title: str | None        # If set, Finalizer uses this instead of LLM output (reindex)
    status: str
    status_message: str
    failure_reason: str | None
    messages: Annotated[list[BaseMessage], add_messages]


class AskAboutWorldState(TypedDict):
    """State for the Ask About World agentic RAG LangGraph graph.

    Per docs/Ask About World.md § Implementation.
    """

    z_bundle_root: str
    zworld_kvp: dict[str, Any]
    user_question: str
    answer: str
    messages: Annotated[list[BaseMessage], add_messages]
