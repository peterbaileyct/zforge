"""LangGraph world creation graph.

Factory function builds a StateGraph(CreateWorldState) with a chunker node,
editor and designer agent nodes, and a deterministic finalizer node.

Tool calls are executed inline within the agent nodes — no ToolNode is used.
This ensures that tool return values (plain dicts) are merged directly into
graph state rather than being stored only as ToolMessage content, which is
how LangGraph 1.x ToolNode behaves with non-Command returns.

Large input documents are split into context-fitting chunks by the chunker
node.  The designer processes one chunk per pass, accumulating partial ZWorld
extractions in state.  After all chunks are processed the finalizer merges the
partial extractions and writes the Z-Bundle.

Implements: src/zforge/graphs/world_creation_graph.py per
docs/World Generation.md and docs/LLM Orchestration.md.
"""

from __future__ import annotations

import concurrent.futures
import logging
import uuid as uuid_mod
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from zforge.graphs.graph_utils import chunk_text, log_node
from zforge.graphs.state import CreateWorldState

log = logging.getLogger(__name__)

from zforge.tools.world_tools import (
    get_zworld_manager,
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
- name: the display name (e.g., "Discworld")
- summary: 1-3 paragraphs describing the world in diegetic terms, suitable for \
helping a player understand the world at a glance
- characters: list, each with a stable ID, one or more names (with optional \
context, e.g. "formal name"), and a narrative history
- locations: list at any granularity with narrative significance (broad regions \
AND specific buildings/landmarks); each with stable ID, name, description, and \
optional sublocations
- events: list of significant occurrences, each with description and a time \
(literal date or relative, e.g. "three years before the story begins")
- mechanics: rules or systems that distinguish how the world operates \
(e.g. "magic exists and is divided between academic wizards and rural witches")
- tropes: recurring story elements and narrative style conventions \
(e.g. "found family themes", "long footnotes detailing world lore")
- species: non-default or notable species; omit if the world maps to Earth species
- occupations: real-world or world-specific occupations of narrative significance
- relationships: typed links between entity IDs \
(e.g., character friends_with character, character present_at event, \
character is_a species, location inside_of location)

Create a ZWorld from the following description of a fictional world:

{input_text}"""

_DESIGNER_CHUNK_SUFFIX = """\

[Note: This is part {chunk_num} of {total_chunks} of the full document. \
Extract all entities you can identify in this section. \
Use the same stable IDs for any entities already seen in earlier parts.]"""

_REJECTION_SYSTEM_PROMPT = (
    "The input text was evaluated as inadequate for world creation. "
    "Please explain clearly why the text is inadequate or inappropriate "
    "as a fictional world description."
)
_LLM_TIMEOUT_SECONDS = 30

_DESIGNER_JSON_SUFFIX = """

Respond with a single JSON object (no markdown fencing, no explanation \
outside the JSON) with exactly these keys:
{
  "name": "...",
  "summary": "...",
  "characters": [{"id": "char_...", "names": [{"name": "...", "context": "..."}], "history": "..."}],
  "locations": [{"id": "loc_...", "name": "...", "description": "...", "sublocations": []}],
  "events": [{"description": "...", "time": "..."}],
  "mechanics": ["..."],
  "tropes": ["..."],
  "species": ["..."],
  "occupations": ["..."],
  "relationships": [{"from_id": "...", "to_id": "...", "type": "..."}]
}"""

# Fraction of context_size (in chars, estimated at 4 chars/token) reserved for
# the input portion of each prompt.  The remainder covers system + human prompts.
_INPUT_FRACTION = 0.55


# --- Node Factories ---


def _make_chunker_node(context_size: int):
    """Return a node that splits input_text into context-fitting chunks."""
    max_chars = int(context_size * _INPUT_FRACTION * 4)

    @log_node("chunker")
    def chunker_node(state: CreateWorldState) -> dict:
        text = state["input_text"]
        chunks = chunk_text(text, max_chars)
        log.info(
            "chunker_node: split %d chars into %d chunk(s) (max_chars=%d)",
            len(text),
            len(chunks),
            max_chars,
        )
        return {"input_chunks": chunks}

    return chunker_node


def _invoke_llm_with_timeout(model, messages, timeout: int):
    """Run *model.invoke* with a timeout enforced via ThreadPoolExecutor."""

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(model.invoke, messages)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise TimeoutError(f"LLM call exceeded {timeout} seconds") from exc


def _parse_validation_response(content: str) -> bool | None:
    """Parse an LLM text response to determine if input was validated.

    Scans for strong positive/negative signals.  Returns True (valid),
    False (invalid), or None (ambiguous).
    """
    normalised = content.strip().lower()
    # Check first line / first word for a clear verdict
    first_line = normalised.split("\n", 1)[0].strip().rstrip(".,!:")
    positive = {"yes", "valid", "adequate", "approved", "acceptable", "true"}
    negative = {"no", "invalid", "inadequate", "rejected", "inappropriate", "false"}
    if first_line in positive:
        return True
    if first_line in negative:
        return False

    # Broader scan — count signal words
    pos_count = sum(1 for w in positive if w in normalised)
    neg_count = sum(1 for w in negative if w in normalised)
    if pos_count > neg_count:
        return True
    if neg_count > pos_count:
        return False
    return None


def _make_editor_node(llm_connector: LlmConnector):
    """Return an editor node that parses plain-text responses instead of tool calls."""
    model = llm_connector.get_model()

    @log_node("editor")
    def editor_node(state: CreateWorldState) -> dict:
        status = state["status"]
        validation_count = state.get("validation_iterations", 0)
        # Validate against the first chunk only — the editor just needs a
        # representative sample to decide if this looks like a world description.
        chunks = state.get("input_chunks") or [state["input_text"]]
        sample = chunks[0]

        if status == "awaiting_rejection_explanation":
            system = _REJECTION_SYSTEM_PROMPT
            action = (
                "Explain why the following text is inadequate as a world "
                f"description. Provide a brief explanation.\n\n{sample}"
            )
        else:
            system = (
                _EDITOR_SYSTEM_PROMPT
                + "\n\nRespond with VALID if this is a clear description of a "
                "fictional world, or INVALID if it is not. Put your verdict "
                "on the first line, then optionally explain."
            )
            action = (
                "Evaluate the following world description:\n\n"
                f"{sample}"
            )

        log.info(
            "editor_node: calling LLM (prompt-based), sample length=%d chars",
            len(sample),
        )
        try:
            response = _invoke_llm_with_timeout(
                model,
                [SystemMessage(content=system), HumanMessage(content=action)],
                _LLM_TIMEOUT_SECONDS,
            )
            log.info("editor_node: LLM call returned")
        except TimeoutError as exc:
            log.warning("editor_node: LLM call timed out — %s", exc)
            return {
                "status": "failed",
                "failure_reason": "LLM call timed out",
                "status_message": "World creation paused: LLM timeout",
            }

        content = str(getattr(response, "content", ""))
        log.info(
            "editor_node: response preview: %r",
            content[:300],
        )

        state_updates: dict = {}

        if status == "awaiting_rejection_explanation":
            explanation = content.strip() or "Input was not recognized as a valid world description"
            log.info("editor_node: rejection explanation length=%d", len(explanation))
            state_updates["status"] = "failed"
            state_updates["failure_reason"] = explanation
            state_updates["status_message"] = "World creation failed: input rejected"
        else:
            verdict = _parse_validation_response(content)
            log.info("editor_node: parsed verdict=%r", verdict)

            if verdict is True:
                state_updates["input_valid"] = True
                state_updates["validation_iterations"] = 1
                state_updates["status"] = "awaiting_generation"
                state_updates["status_message"] = "Input validated"
            elif verdict is False:
                state_updates["input_valid"] = False
                state_updates["validation_iterations"] = 1
                state_updates["status"] = "awaiting_validation"
                state_updates["status_message"] = "Input validation failed"
            else:
                log.warning(
                    "editor_node: ambiguous LLM response — counting as a "
                    "failed validation (validation_count=%d)",
                    validation_count,
                )
                state_updates["validation_iterations"] = 1

            effective_status = state_updates.get("status", status)
            new_val_count = validation_count + state_updates.get("validation_iterations", 0)
            if (
                effective_status == "awaiting_validation"
                and new_val_count >= MAX_VALIDATION_ATTEMPTS
            ):
                log.warning(
                    "editor_node: max validation attempts (%d) reached —"
                    " switching to explanation mode",
                    MAX_VALIDATION_ATTEMPTS,
                )
                state_updates["status"] = "awaiting_rejection_explanation"

        return {"messages": [response], **state_updates}

    return editor_node


def _make_designer_node(llm_connector: LlmConnector):
    """Return a designer node that parses JSON output with a timeout."""
    model = llm_connector.get_model()

    @log_node("designer")
    def designer_node(state: CreateWorldState) -> dict:
        import json
        import re

        chunks = state.get("input_chunks") or [state["input_text"]]
        idx = state.get("current_chunk_index", 0)
        total = len(chunks)
        chunk = chunks[idx]

        if total > 1:
            chunk_annotation = _DESIGNER_CHUNK_SUFFIX.format(
                chunk_num=idx + 1, total_chunks=total
            )
        else:
            chunk_annotation = ""

        system = (
            _DESIGNER_SYSTEM_PROMPT_TEMPLATE.format(
                input_text=chunk + chunk_annotation
            )
            + _DESIGNER_JSON_SUFFIX
        )
        log.info(
            "designer_node: processing chunk %d/%d (%d chars)",
            idx + 1,
            total,
            len(chunk),
        )
        try:
            response = _invoke_llm_with_timeout(
                model,
                [
                    SystemMessage(content=system),
                    HumanMessage(content="Build the specified ZWorld. Respond ONLY with the JSON object."),
                ],
                _LLM_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            log.warning("designer_node: LLM call timed out — %s", exc)
            return {
                "status": "failed",
                "failure_reason": "LLM call timed out",
                "status_message": "World creation paused: LLM timeout",
            }

        content = str(getattr(response, "content", ""))
        log.info(
            "designer_node: LLM responded — content length=%d  preview: %r",
            len(content),
            content[:300],
        )

        state_updates: dict = {}

        parsed = None
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if fence_match:
            try:
                parsed = json.loads(fence_match.group(1))
            except json.JSONDecodeError:
                pass

        if parsed is None:
            brace_match = re.search(r"\{", content)
            if brace_match:
                json_candidate = content[brace_match.start():]
                try:
                    parsed = json.loads(json_candidate)
                except json.JSONDecodeError:
                    last_brace = json_candidate.rfind("}")
                    while last_brace > 0:
                        try:
                            parsed = json.loads(json_candidate[: last_brace + 1])
                            break
                        except json.JSONDecodeError:
                            last_brace = json_candidate.rfind("}", 0, last_brace)

        if parsed and isinstance(parsed, dict):
            log.info(
                "designer_node: parsed JSON — name=%r  chars=%d  locs=%d  rels=%d",
                parsed.get("name"),
                len(parsed.get("characters", [])),
                len(parsed.get("locations", [])),
                len(parsed.get("relationships", [])),
            )
            partial = {
                "name": parsed.get("name", "Unknown World"),
                "summary": parsed.get("summary", ""),
                "characters": parsed.get("characters", []),
                "locations": parsed.get("locations", []),
                "events": parsed.get("events", []),
                "mechanics": parsed.get("mechanics", []),
                "tropes": parsed.get("tropes", []),
                "species": parsed.get("species", []),
                "occupations": parsed.get("occupations", []),
                "relationships": parsed.get("relationships", []),
            }
            state_updates["partial_zworlds"] = [partial]
            state_updates["current_chunk_index"] = 1
            state_updates["status"] = "awaiting_generation"
            state_updates["status_message"] = f"Extracted entities from chunk for '{partial['name']}'"
        else:
            log.warning(
                "designer_node: could not parse JSON from LLM response — skipping chunk %d",
                idx,
            )
            state_updates["current_chunk_index"] = 1

        return {"messages": [response], **state_updates}

    return designer_node


def _make_finalizer_node():
    """Return a deterministic node that merges partial ZWorld extractions and writes the Z-Bundle."""

    @log_node("finalizer")
    def finalizer_node(state: CreateWorldState) -> dict:
        from zforge.models.zworld import (
            Character,
            CharacterName,
            Event,
            Location,
            Mechanic,
            Occupation,
            Relationship,
            Species,
            Trope,
            ZWorld,
        )

        partials = state.get("partial_zworlds") or []
        if not partials:
            log.error("finalizer_node: no partial_zworlds in state")
            return {
                "status": "failed",
                "failure_reason": "Designer produced no ZWorld data",
                "status_message": "World creation failed: no data extracted",
            }

        # Name and summary come from the first (primary) partial.
        name = partials[0].get("name", "Unknown World")
        summaries = [p.get("summary", "") for p in partials if p.get("summary")]
        summary = summaries[0] if summaries else ""

        char_map: dict = {}
        loc_map: dict = {}
        event_seen: set = set()
        events: list = []
        mechanics: list = []
        tropes: list = []
        species: list = []
        occupations: list = []
        rel_seen: set = set()
        relationships: list = []

        for partial in partials:
            for c in partial.get("characters", []):
                cid = c.get("id")
                if cid and cid not in char_map:
                    char_map[cid] = c
            for loc in partial.get("locations", []):
                lid = loc.get("id")
                if lid and lid not in loc_map:
                    loc_map[lid] = loc
            for e in partial.get("events", []):
                key = e.get("description", "")[:80]
                if key not in event_seen:
                    event_seen.add(key)
                    events.append(e)
            for item in partial.get("mechanics", []):
                if item not in mechanics:
                    mechanics.append(item)
            for item in partial.get("tropes", []):
                if item not in tropes:
                    tropes.append(item)
            for item in partial.get("species", []):
                if item not in species:
                    species.append(item)
            for item in partial.get("occupations", []):
                if item not in occupations:
                    occupations.append(item)
            for r in partial.get("relationships", []):
                key = (r.get("from_id"), r.get("to_id"), r.get("type"))
                if key not in rel_seen:
                    rel_seen.add(key)
                    relationships.append(r)

        log.info(
            "finalizer_node: merged %d partial(s) — %d chars, %d locs, "
            "%d rels, %d events",
            len(partials), len(char_map), len(loc_map),
            len(relationships), len(events),
        )

        def _parse_names(raw_names: list[dict]) -> list[CharacterName]:
            return [
                CharacterName(name=n["name"], context=n.get("context"))
                for n in raw_names
                if "name" in n
            ]

        def _parse_locations(raw_locs: list[dict]) -> list[Location]:
            result = []
            for loc in raw_locs:
                result.append(Location(
                    id=loc["id"],
                    name=loc.get("name", ""),
                    description=loc.get("description", ""),
                    sublocations=_parse_locations(loc.get("sublocations", [])),
                ))
            return result

        slug = name.lower().replace(" ", "-")
        zworld = ZWorld(
            title=name,
            slug=slug,
            uuid=str(uuid_mod.uuid4()),
            summary=summary,
            characters=[
                Character(
                    id=c["id"],
                    names=_parse_names(c.get("names", [])),
                    history=c.get("history", ""),
                )
                for c in char_map.values()
            ],
            locations=_parse_locations(list(loc_map.values())),
            events=[
                Event(description=e["description"], time=e.get("time", ""))
                for e in events
            ],
            mechanics=[Mechanic(text=m) for m in mechanics],
            tropes=[Trope(text=t) for t in tropes],
            species=[Species(text=s) for s in species],
            occupations=[Occupation(text=o) for o in occupations],
            relationships=[
                Relationship(from_id=r["from_id"], to_id=r["to_id"], type=r["type"])
                for r in relationships
                if r.get("from_id") and r.get("to_id") and r.get("type")
            ],
        )

        mgr = get_zworld_manager()
        if mgr is not None:
            mgr.create(zworld)
        else:
            log.error("finalizer_node: ZWorldManager not injected — Z-Bundle not written")

        return {
            "status": "complete",
            "status_message": f"World '{name}' created successfully",
        }

    return finalizer_node


# --- Routing ---


def _route_after_editor(state: CreateWorldState) -> str:
    status = state["status"]
    validation_count = state.get("validation_iterations", 0)
    log.info(
        "_route_after_editor: status=%r  validation_iterations=%d/%d",
        status, validation_count, MAX_VALIDATION_ATTEMPTS,
    )
    if status == "awaiting_generation":
        decision = "designer"
    elif status in ("awaiting_validation", "awaiting_rejection_explanation"):
        decision = "editor"
    elif status in ("complete", "failed"):
        decision = "end"
    else:
        log.error("_route_after_editor: unrecognised status=%r — routing to end", status)
        decision = "end"
    log.info("_route_after_editor: decision=%r", decision)
    return decision


def _route_after_designer(state: CreateWorldState) -> str:
    status = state["status"]
    chunks = state.get("input_chunks") or []
    chunk_idx = state.get("current_chunk_index", 0)
    log.info(
        "_route_after_designer: status=%r  chunk=%d/%d",
        status, chunk_idx, len(chunks),
    )
    if status == "awaiting_generation":
        if not chunks or chunk_idx >= len(chunks):
            decision = "finalize"
        else:
            decision = "designer"
    elif status in ("complete", "failed"):
        decision = "end"
    else:
        log.error("_route_after_designer: unrecognised status=%r — routing to end", status)
        decision = "end"
    log.info("_route_after_designer: decision=%r", decision)
    return decision


# --- Graph Builder ---


def build_create_world_graph(llm_connector: LlmConnector):
    """Build and compile the world creation LangGraph StateGraph."""
    context_size = llm_connector.get_context_size()
    log.info("build_create_world_graph: context_size=%d", context_size)

    graph = StateGraph(CreateWorldState)

    graph.add_node("chunker", _make_chunker_node(context_size))
    graph.add_node("editor", _make_editor_node(llm_connector))
    graph.add_node("designer", _make_designer_node(llm_connector))
    graph.add_node("finalize", _make_finalizer_node())

    graph.set_entry_point("chunker")
    graph.add_edge("chunker", "editor")
    graph.add_edge("finalize", END)
    graph.add_conditional_edges("editor", _route_after_editor, {
        "editor": "editor",
        "designer": "designer",
        "end": END,
    })
    graph.add_conditional_edges("designer", _route_after_designer, {
        "designer": "designer",
        "finalize": "finalize",
        "end": END,
    })

    return graph.compile()

