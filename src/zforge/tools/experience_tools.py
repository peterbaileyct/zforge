"""LangGraph @tool functions for experience generation.

Each tool corresponds to a decision point in the experience generation graph.
Tools return Command(update={...}) so LangGraph's ToolNode applies state
changes directly. Counter fields return 1 to increment or 0 for no change.

Implements: src/zforge/tools/experience_tools.py per
docs/Experience Generation.md and docs/Managers, Processes, and MCP Server.md.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command

if TYPE_CHECKING:
    from zforge.services.if_engine.if_engine_connector import IfEngineConnector

# Module-level reference set by the graph builder before compilation.
_if_engine_connector: IfEngineConnector | None = None

# Tracks the status just before each tool call so tools can record 'from_status'.
_current_status: str | None = None

MAX_ITERATIONS = 5


def set_if_engine_connector(connector: IfEngineConnector) -> None:
    """Inject the IfEngineConnector dependency for tool functions."""
    global _if_engine_connector
    _if_engine_connector = connector


def set_current_status(status: str) -> None:
    """Called by each agent node before invoking the LLM to capture from_status."""
    global _current_status
    _current_status = status


def _log_entry(action: str, to_status: str, rationale: str) -> dict[str, Any]:
    """Build a single action log entry dict."""
    return {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "from_status": _current_status or "unknown",
        "to_status": to_status,
        "action": action,
        "rationale": rationale,
    }


@tool
def experience_author_submit_outline(
    outline: str,
    tech_notes: str,
    rationale: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Author submits the story outline and technical exception notes.
    Call when the Author has completed the outline based on the inputs.
    rationale: brief explanation of the creative choices made in this outline.
    """
    to_status = "awaiting_outline_review"
    return Command(update={
        "outline": outline,
        "tech_notes": tech_notes,
        "status": to_status,
        "status_message": "Author submitted outline",
        "current_rationale": rationale,
        "action_log": [_log_entry("Author submitted outline", to_status, rationale)],
        "outline_iterations": 0,
        "script_compile_iterations": 0,
        "author_review_iterations": 0,
        "tech_edit_iterations": 0,
        "story_edit_iterations": 0,
        "messages": [ToolMessage(content="Author submitted outline", tool_call_id=tool_call_id)],
    })


@tool
def experience_scripter_approve_outline(
    rationale: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Scripter approves the outline as suitable for scripting.
    Call when the outline is feasible and aligned with preferences.
    rationale: brief explanation of why the outline is acceptable.
    """
    to_status = "awaiting_script"
    return Command(update={
        "status": to_status,
        "status_message": "Scripter approves outline",
        "current_rationale": rationale,
        "action_log": [_log_entry("Scripter approves outline", to_status, rationale)],
        "outline_iterations": 0,
        "script_compile_iterations": 0,
        "author_review_iterations": 0,
        "tech_edit_iterations": 0,
        "story_edit_iterations": 0,
        "messages": [ToolMessage(content="Scripter approves outline", tool_call_id=tool_call_id)],
    })


@tool
def experience_scripter_reject_outline(
    outline_notes: str,
    rationale: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Scripter rejects the outline with feedback (Outline Notes).
    Call when the outline has issues that need Author revision.
    rationale: brief explanation of the specific concerns with the outline.
    """
    to_status = "awaiting_outline_revision"
    return Command(update={
        "outline_notes": outline_notes,
        "outline_iterations": 1,
        "status": to_status,
        "status_message": "Scripter requests outline revision",
        "current_rationale": rationale,
        "action_log": [_log_entry("Scripter requests outline revision", to_status, rationale)],
        "script_compile_iterations": 0,
        "author_review_iterations": 0,
        "tech_edit_iterations": 0,
        "story_edit_iterations": 0,
        "messages": [ToolMessage(content="Scripter requests outline revision", tool_call_id=tool_call_id)],
    })


@tool
async def experience_scripter_submit_script(
    script: str,
    rationale: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Scripter submits a complete script. Triggers compilation validation
    via IfEngineConnector.build(). Call when the Scripter has written or
    revised a complete script.
    rationale: brief explanation of the scripting approach taken.
    """
    if _if_engine_connector is None:
        raise RuntimeError("IfEngineConnector not configured")

    build_result = await _if_engine_connector.build(script)

    if build_result.errors:
        to_status = "awaiting_script_fix"
        return Command(update={
            "script": script,
            "compiler_errors": build_result.errors,
            "script_compile_iterations": 1,
            "status": to_status,
            "status_message": f"Compilation failed with {len(build_result.errors)} error(s)",
            "current_rationale": rationale,
            "action_log": [_log_entry("Scripter submitted script (compilation failed)", to_status, rationale)],
            "outline_iterations": 0,
            "author_review_iterations": 0,
            "tech_edit_iterations": 0,
            "story_edit_iterations": 0,
            "messages": [ToolMessage(content="Compilation failed", tool_call_id=tool_call_id)],
        })
    to_status = "awaiting_author_review"
    return Command(update={
        "script": script,
        "compiled_output": build_result.output,
        "compiler_errors": [],
        "script_compile_iterations": 0,
        "status": to_status,
        "status_message": "Script compiled successfully",
        "current_rationale": rationale,
        "action_log": [_log_entry("Scripter submitted script (compiled OK)", to_status, rationale)],
        "outline_iterations": 0,
        "author_review_iterations": 0,
        "tech_edit_iterations": 0,
        "story_edit_iterations": 0,
        "messages": [ToolMessage(content="Script compiled successfully", tool_call_id=tool_call_id)],
    })


@tool
def experience_author_approve_script(
    rationale: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Author approves the script as matching the outline.
    Call when the script satisfactorily implements the Author's vision.
    rationale: brief explanation of why the script meets the outline.
    """
    # Editing order determined by conditional edge reading preferences
    to_status = "awaiting_tech_edit"
    return Command(update={
        "status": to_status,
        "status_message": "Author approves script",
        "current_rationale": rationale,
        "action_log": [_log_entry("Author approves script", to_status, rationale)],
        "outline_iterations": 0,
        "script_compile_iterations": 0,
        "author_review_iterations": 0,
        "tech_edit_iterations": 0,
        "story_edit_iterations": 0,
        "messages": [ToolMessage(content="Author approves script", tool_call_id=tool_call_id)],
    })


@tool
def experience_author_reject_script(
    script_notes: str,
    rationale: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Author rejects the script with feedback (Script Notes).
    Call when the script diverges unacceptably from the outline.
    rationale: brief explanation of the specific divergences found.
    """
    to_status = "awaiting_script_revision"
    return Command(update={
        "script_notes": script_notes,
        "author_review_iterations": 1,
        "status": to_status,
        "status_message": "Author requests script revision",
        "current_rationale": rationale,
        "action_log": [_log_entry("Author requests script revision", to_status, rationale)],
        "outline_iterations": 0,
        "script_compile_iterations": 0,
        "tech_edit_iterations": 0,
        "story_edit_iterations": 0,
        "messages": [ToolMessage(content="Author requests script revision", tool_call_id=tool_call_id)],
    })


@tool
def experience_techeditor_approve(
    rationale: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Technical Editor approves the script — no logical inconsistencies
    exceeding player tolerance. Call when the script passes tech review.
    rationale: brief explanation of what was checked and why no issues were found.
    """
    to_status = "awaiting_story_edit"
    return Command(update={
        "status": to_status,
        "status_message": "Technical Editor approves",
        "current_rationale": rationale,
        "action_log": [_log_entry("Technical Editor approves", to_status, rationale)],
        "outline_iterations": 0,
        "script_compile_iterations": 0,
        "author_review_iterations": 0,
        "tech_edit_iterations": 0,
        "story_edit_iterations": 0,
        "messages": [ToolMessage(content="Technical Editor approves", tool_call_id=tool_call_id)],
    })


@tool
def experience_techeditor_reject(
    tech_edit_report: str,
    rationale: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Technical Editor rejects the script with a Tech Edit Report listing
    logical inconsistencies. Call when issues exceed player tolerance.
    rationale: brief summary of the most significant issues found.
    """
    to_status = "awaiting_tech_fix"
    return Command(update={
        "tech_edit_report": tech_edit_report,
        "tech_edit_iterations": 1,
        "status": to_status,
        "status_message": "Technical Editor found issues",
        "current_rationale": rationale,
        "action_log": [_log_entry("Technical Editor found issues", to_status, rationale)],
        "outline_iterations": 0,
        "script_compile_iterations": 0,
        "author_review_iterations": 0,
        "story_edit_iterations": 0,
        "messages": [ToolMessage(content="Technical Editor found issues", tool_call_id=tool_call_id)],
    })


@tool
def experience_storyeditor_approve(
    rationale: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Story Editor approves the script — it aligns well with player
    preferences. Call when the script satisfactorily matches preferences.
    rationale: brief explanation of how the script meets player preferences.
    """
    to_status = "complete"
    return Command(update={
        "status": to_status,
        "status_message": "Story Editor approves — experience complete",
        "current_rationale": rationale,
        "action_log": [_log_entry("Story Editor approves", to_status, rationale)],
        "outline_iterations": 0,
        "script_compile_iterations": 0,
        "author_review_iterations": 0,
        "tech_edit_iterations": 0,
        "story_edit_iterations": 0,
        "messages": [ToolMessage(content="Story Editor approves", tool_call_id=tool_call_id)],
    })


@tool
def experience_storyeditor_reject(
    story_edit_report: str,
    rationale: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Story Editor rejects the script with a Story Edit Report listing
    preference mismatches. Call when the script meaningfully deviates
    from what the player requested or prefers.
    rationale: brief summary of the preference mismatches found.
    """
    to_status = "awaiting_story_fix"
    return Command(update={
        "story_edit_report": story_edit_report,
        "story_edit_iterations": 1,
        "status": to_status,
        "status_message": "Story Editor requests changes",
        "current_rationale": rationale,
        "action_log": [_log_entry("Story Editor requests changes", to_status, rationale)],
        "outline_iterations": 0,
        "script_compile_iterations": 0,
        "author_review_iterations": 0,
        "tech_edit_iterations": 0,
        "messages": [ToolMessage(content="Story Editor requests changes", tool_call_id=tool_call_id)],
    })


# Convenience list for graph construction
all_experience_tools = [
    experience_author_submit_outline,
    experience_scripter_approve_outline,
    experience_scripter_reject_outline,
    experience_scripter_submit_script,
    experience_author_approve_script,
    experience_author_reject_script,
    experience_techeditor_approve,
    experience_techeditor_reject,
    experience_storyeditor_approve,
    experience_storyeditor_reject,
]
