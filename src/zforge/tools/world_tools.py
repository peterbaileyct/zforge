"""LangGraph @tool functions for world creation.

Tool functions are invoked directly by the editor and designer nodes (not via
ToolNode) so that state updates are returned as plain dicts in the same pass.
The ``@tool`` decorator is kept so ``model.bind_tools()`` can still advertise
the correct JSON schema to the LLM.

Implements: src/zforge/tools/world_tools.py per
docs/World Generation.md and docs/Managers, Processes, and MCP Server.md.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import tool

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from zforge.managers.zworld_manager import ZWorldManager

# Module-level reference set by the graph builder before compilation.
_zworld_manager: ZWorldManager | None = None

MAX_VALIDATION_ATTEMPTS = 5


def set_zworld_manager(manager: ZWorldManager) -> None:
    """Inject the ZWorldManager dependency for tool functions."""
    global _zworld_manager
    _zworld_manager = manager


def get_zworld_manager() -> ZWorldManager | None:
    """Return the injected ZWorldManager (used by the finalizer node)."""
    return _zworld_manager


@tool
def world_validate_input(valid: bool) -> dict[str, Any]:
    """
    Editor validates whether the input text is a clear description of a
    fictional world. Call with valid=true if the description is adequate,
    or valid=false if it is not.
    """
    new_status = "awaiting_generation" if valid else "awaiting_validation"
    log.info(
        "[tool:world_validate_input] valid=%r  -> status=%r",
        valid, new_status,
    )
    return {
        "input_valid": valid,
        "validation_iterations": 1,
        "status": new_status,
        "status_message": "Input validated" if valid else "Input validation failed",
    }


@tool
def world_create_zworld(
    name: str,
    summary: str,
    characters: list[dict[str, Any]],
    locations: list[dict[str, Any]],
    events: list[dict[str, Any]],
    mechanics: list[str],
    tropes: list[str],
    species: list[str],
    occupations: list[str],
    relationships: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Designer creates a ZWorld from the given properties.
    Call with the full ZWorld specification derived from the input description.

    Parameters:
        name: Display name (e.g. "Discworld").
        summary: 1-3 paragraphs describing the world in diegetic terms.
        characters: List of dicts with keys: id, names (list of {name, context?}), history.
        locations: List of dicts with keys: id, name, description, sublocations? (recursive).
        events: List of dicts with keys: description, time.
        mechanics: List of strings describing world mechanics.
        tropes: List of strings describing story tropes.
        species: List of strings for notable species (omit if Earth-default).
        occupations: List of strings for narratively significant occupations.
        relationships: List of dicts with keys: from_id, to_id, type.
    """
    # Store raw extracted data as a partial dict.  The finalizer node will
    # merge extractions from all chunks and write the Z-Bundle once done.
    log.info(
        "[tool:world_create_zworld] name=%r  chars=%d  locs=%d  rels=%d",
        name, len(characters), len(locations), len(relationships),
    )
    partial = {
        "name": name,
        "summary": summary,
        "characters": characters,
        "locations": locations,
        "events": events,
        "mechanics": mechanics,
        "tropes": tropes,
        "species": species,
        "occupations": occupations,
        "relationships": relationships,
    }
    return {
        "partial_zworlds": [partial],
        "current_chunk_index": 1,        # operator.add increments the counter
        "status": "awaiting_generation",  # router decides: next chunk or finalize
        "status_message": f"Extracted entities from chunk for '{name}'",
    }


@tool
def world_explain_rejection(explanation: str) -> dict[str, Any]:
    """
    Editor explains why the input text is inadequate or inappropriate
    as a world description. Called after validation has failed.
    """
    log.warning("[tool:world_explain_rejection] input rejected: %r", explanation[:120])
    return {
        "status": "failed",
        "failure_reason": explanation,
        "status_message": "World creation failed: input rejected",
    }


# Convenience list for graph construction
all_world_tools = [world_validate_input, world_create_zworld, world_explain_rejection]
