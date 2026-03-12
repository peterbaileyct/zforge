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
from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class ExperienceGenerationState(TypedDict):
    """State for the experience generation LangGraph graph.

    Per docs/Experience Generation.md § Implementation.
    """

    # Inputs (set at initialization)
    zworld_kvp: dict
    world_slug: str
    z_bundle_root: str
    preferences: dict
    player_prompt: str | None

    # Artifacts (set by agent nodes during execution)
    outline: str | None
    research_notes: str | None
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

    # Iteration counters — use operator.add reducer so nodes return 1 to increment
    outline_review_count: Annotated[int, operator.add]
    prose_review_count: Annotated[int, operator.add]
    compile_fix_count: Annotated[int, operator.add]
    script_rewrite_count: Annotated[int, operator.add]

    # Status
    status: str
    status_message: str
    failure_reason: str | None

    # LangGraph message history — for observability
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
    documents: list           # contextualized large-chunk Documents (used for graph ingestion)
    retrieval_documents: list  # small re-split Documents with breadcrumbs (used for vector ingestion)
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
    zworld_kvp: dict | None
    conflicting_slug: str | None    # Set by duplicate_check if a same-title world exists
    overwrite_decision: str | None  # "overwrite" | "cancel" | None
    status: str
    status_message: str
    failure_reason: str | None
    messages: Annotated[list, add_messages]


class AskAboutWorldState(TypedDict):
    """State for the Ask About World agentic RAG LangGraph graph.

    Per docs/Ask About World.md § Implementation.
    """

    z_bundle_root: str
    zworld_kvp: dict
    user_question: str
    answer: str
    messages: Annotated[list, add_messages]
