"""LangGraph @tool functions for world creation.

Each tool corresponds to a decision point in the world creation graph.
Tools return dicts of state field updates merged by ToolNode.

Implements: src/zforge/tools/world_tools.py per
docs/World Generation.md and docs/Managers, Processes, and MCP Server.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.tools import tool

if TYPE_CHECKING:
    from zforge.managers.zworld_manager import ZWorldManager

# Module-level reference set by the graph builder before compilation.
_zworld_manager: ZWorldManager | None = None

MAX_VALIDATION_ATTEMPTS = 5


def set_zworld_manager(manager: ZWorldManager) -> None:
    """Inject the ZWorldManager dependency for tool functions."""
    global _zworld_manager
    _zworld_manager = manager


@tool
def world_validate_input(valid: bool) -> dict[str, Any]:
    """
    Editor validates whether the input text is a clear description of a
    fictional world. Call with valid=true if the description is adequate,
    or valid=false if it is not.
    """
    result: dict[str, Any] = {
        "input_valid": valid,
        "validation_iterations": 1,
        "status_message": "Input validated" if valid else "Input validation failed",
    }
    if valid:
        result["status"] = "awaiting_generation"
    else:
        # Will be checked by conditional edge for retry vs. fail
        result["status"] = "awaiting_validation"
    return result


@tool
def world_create_zworld(
    name: str,
    locations: list[dict[str, Any]],
    characters: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Designer creates a ZWorld from the given properties.
    Call with the full ZWorld specification derived from the input description.
    """
    from zforge.models.zworld import ZWorld

    # Generate id from name
    zworld_id = name.lower().replace(" ", "-")
    zworld_data = {
        "id": zworld_id,
        "name": name,
        "locations": locations,
        "characters": characters,
        "relationships": relationships,
        "events": events,
    }
    zworld = ZWorld.from_dict(zworld_data)

    if _zworld_manager is not None:
        _zworld_manager.create(zworld)

    return {
        "status": "complete",
        "status_message": f"World '{name}' created successfully",
    }


@tool
def world_explain_rejection(explanation: str) -> dict[str, Any]:
    """
    Editor explains why the input text is inadequate or inappropriate
    as a world description. Called after validation has failed.
    """
    return {
        "status": "failed",
        "failure_reason": explanation,
        "status_message": "World creation failed: input rejected",
    }


# Convenience list for graph construction
all_world_tools = [world_validate_input, world_create_zworld, world_explain_rejection]
