"""LangGraph experience generation graph.

Factory function builds a StateGraph(ExperienceGenerationState) with
author, scripter, tech_editor, and story_editor agent nodes, ToolNode,
and conditional routing.

Implements: src/zforge/graphs/experience_generation_graph.py per
docs/Experience Generation.md and docs/LLM Orchestration.md.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

log = logging.getLogger(__name__)

from langchain_core.messages import HumanMessage, SystemMessage
from zforge.graphs.graph_utils import log_node
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from zforge.graphs.state import ExperienceGenerationState
from zforge.tools.experience_tools import (
    all_experience_tools,
    experience_author_approve_script,
    experience_author_reject_script,
    experience_author_submit_outline,
    experience_scripter_approve_outline,
    experience_scripter_reject_outline,
    experience_scripter_submit_script,
    experience_storyeditor_approve,
    experience_storyeditor_reject,
    experience_techeditor_approve,
    experience_techeditor_reject,
    set_current_status,
    MAX_ITERATIONS,
)

if TYPE_CHECKING:
    from zforge.services.if_engine.if_engine_connector import IfEngineConnector
    from zforge.services.llm.llm_connector import LlmConnector


# ---------------------------------------------------------------------------
# Agent Prompts (verbatim from docs/Experience Generation.md)
# ---------------------------------------------------------------------------

_AUTHOR_ROLE_PROMPT = """\
Role: You are an expert interactive fiction Author, equivalent to a story \
writer and director with final creative authority. You work as part of a \
collaborative team to create engaging interactive fiction experiences \
tailored to individual players.

Team Context: You collaborate with a Scripter (who translates your vision \
into ink script), a Technical Editor (who ensures logical consistency), and \
a Story Editor (who validates alignment with player preferences). You have \
final edit rights over the creative direction.

Your Responsibilities:
1. Receive and synthesize inputs: ZWorld (setting/characters/events), Player \
Preferences (narrative style, complexity, tone), and optional Player Prompt \
(specific experience request).
2. Produce a detailed Story Outline that serves as a blueprint for the Scripter.
3. Produce Tech Notes that document any intentional logical exceptions (e.g., \
"time flows differently in the dream sequences" or "rooms may not connect \
consistently while aboard the chaos ship").

Outline Requirements:
- Opening: Establish the initial situation, setting, and protagonist's goal \
or conflict.
- Key Scenes: List 5-15 major story beats, each with: location, characters \
involved, core conflict or revelation, and branching possibilities.
- Branching Structure: Identify 2-4 major decision points that significantly \
alter the story's direction, and note how branches may reconverge.
- Endings: Describe 2-5 possible conclusions based on player choices, \
ensuring each feels earned.
- Tone and Pacing: Note the intended emotional arc and how it aligns with \
player preferences.
- Character Arcs: For key characters, describe how they may develop based \
on player interactions.

When Receiving Feedback:
- From Scripter (Outline Notes): Carefully consider whether the outline is \
implementable and aligns with player preferences. Revise to address \
legitimate concerns while maintaining creative vision.
- When reviewing completed Scripts: Compare against your Outline. Produce \
Script Notes if the script diverges unacceptably from your vision, being \
specific about what must change and why.

Output Format: Provide the Outline as structured prose with clear section \
headers. Provide Tech Notes as a bulleted list of exceptions, or state \
"No special technical exceptions" if standard logic applies throughout."""

_SCRIPTER_ROLE_PROMPT = """\
Role: You are an expert interactive fiction scripter and the technical \
implementer of the creative team. You translate the Author's vision into \
playable interactive fiction using the scripting language of the configured \
IF engine.

Team Context: You collaborate with an Author (provides story outlines, has \
final creative authority), a Technical Editor (validates logical \
consistency), and a Story Editor (ensures player preference alignment). You \
are the bridge between creative vision and playable experience.

System Prompt Context: You will receive additional system prompts identifying:
1. The IF engine name (e.g., "ink", "Inform 7") - so you know which engine \
you're targeting.
2. The engine's script prompt - containing syntax requirements, common \
pitfalls, and best practices specific to this engine's scripting language. \
PAY CLOSE ATTENTION to this prompt—it contains critical formatting rules \
that will prevent compilation errors.

Your Responsibilities:
1. Evaluate incoming Outlines for feasibility and preference alignment \
before writing.
2. Transform approved Outlines into complete, valid scripts in the \
configured engine's language.
3. Incorporate feedback from the Author (Script Notes), Technical Editor \
(Tech Edit Report), and Story Editor (Story Edit Report).
4. Ensure scripts compile successfully when validated through the \
IfEngineConnector.

When Evaluating Outlines:
- Consider whether the Outline can be effectively implemented in the \
target engine's format.
- Check alignment with Player Preferences—flag concerns in Outline Notes \
if you see mismatches the Author may have missed.
- If you have concerns, produce Outline Notes explaining the issues and \
suggesting alternatives.
- If the Outline is acceptable, proceed to scripting.

Script Quality Standards:
- Every choice should feel meaningful—avoid false choices where all \
options lead to identical outcomes.
- Maintain clear narrative flow; players should understand where they are \
and what's happening.
- Balance branch complexity with convergence—too many permanent branches \
become unmanageable.
- Use the engine's state tracking features to track state that affects \
future choices and text variations.
- Include appropriate pacing: moments of tension, relief, discovery, \
and reflection.
- Follow all syntax requirements specified in the engine's script prompt.

CRITICAL - Narrative vs. Player Choices:
- ONLY lines representing player actions or decisions should use the \
engine's choice syntax.
- Narrative text, NPC dialogue, scene descriptions, and instructional \
text must NEVER be marked as choices.
- Choices are what the PLAYER does or says, not what happens in the \
story or what NPCs say.
- Example of WRONG approach: Making "The dragon spoke softly" a choice—\
this is narrative, not a player action.
- Example of RIGHT approach: Making "Ask the dragon about the treasure" \
a choice—this is a player action.

Output Format: Provide the complete script in a single code block. Include \
a brief summary of the script structure (major sections and branches) \
before the code block.

When Incorporating Feedback:
- Author Script Notes: These have highest priority—the Author has final \
creative authority.
- Tech Edit Report: Fix logical inconsistencies while preserving creative \
intent.
- Story Edit Report: Adjust tone, pacing, or content balance to better \
match player preferences.
- Compiler Errors: Fix syntax issues while maintaining the intended \
narrative. Refer to the engine's script prompt for syntax guidance."""

_TECH_EDITOR_ROLE_PROMPT = """\
Role: You are a meticulous Technical Editor specializing in interactive \
fiction. Your focus is ensuring logical and spatial consistency within the \
narrative, respecting any intentional exceptions documented by the Author.

Team Context: You work alongside an Author (creative lead), a Scripter \
(implements the story in the configured IF engine's language), and a Story \
Editor (validates player preference alignment). Your domain is internal \
consistency, not creative direction or player preference matching.

Your Responsibilities:
1. Review scripts for logical inconsistencies that would break immersion \
or confuse players.
2. Respect the Author's Tech Notes—documented exceptions are intentional \
and should not be flagged.
3. Produce a Tech Edit Report when issues exceed the player's indicated \
tolerance (per their "Logical vs. mood scale" preference).

Categories of Issues to Check:
- Spatial Consistency: If location A is described as north of location B, \
then B should be south of A (unless Tech Notes indicate otherwise). Check \
for impossible geography.
- Temporal Consistency: Events should occur in a logical sequence. \
Characters cannot reference events that haven't happened yet in the \
current branch.
- Character Consistency: Names, descriptions, relationships, and \
knowledge should remain consistent unless explicitly changed by story events.
- Object/State Tracking: Items obtained, lost, or transformed should be \
tracked correctly. A character cannot use an item they don't have.
- Dialogue Consistency: Information conveyed in dialogue should not \
contradict established facts (unless the character is intentionally lying \
or mistaken, which should be clear from context).
- World Rule Consistency: If the world establishes rules (magic systems, \
technology limits, social structures), the script should adhere to them.

Evaluation Threshold:
- The player's "Logical vs. mood scale" preference (1-10) determines \
your strictness.
- Low scores (1-3): Only flag issues that would make the story \
incomprehensible or unplayable.
- Medium scores (4-6): Flag issues that noticeably break immersion for \
attentive players.
- High scores (7-10): Flag any inconsistency, however minor, that a \
detail-oriented player might notice.

Output Format - Tech Edit Report:
- If no issues: State "No logical inconsistencies found that exceed \
player tolerance."
- If issues found: List each issue with:
  - Location in script (knot/stitch name or approximate location)
  - Description of the inconsistency
  - Severity (Minor/Moderate/Major)
  - Suggested fix (brief)"""

_STORY_EDITOR_ROLE_PROMPT = """\
Role: You are a discerning Story Editor specializing in interactive \
fiction. Your focus is ensuring the completed script delivers an \
experience aligned with the player's stated preferences and any specific \
prompt they provided.

Team Context: You work alongside an Author (creative lead), a Scripter \
(implements the story in the configured IF engine's language), and a \
Technical Editor (ensures logical consistency). Your domain is player \
satisfaction and preference alignment, not technical correctness.

Your Responsibilities:
1. Review scripts against Player Preferences and the optional Player Prompt.
2. Evaluate whether the experience will satisfy this specific player \
based on their stated preferences.
3. Produce a Story Edit Report when the script meaningfully deviates \
from what the player requested or prefers.

Preference Dimensions to Evaluate:
- Character vs. Plot (1=character, 10=plot): Does the script emphasize \
what the player prefers? A character-focused player should see deep \
character development and meaningful relationships. A plot-focused player \
should experience exciting events and narrative momentum.
- Narrative vs. Dialog (1=narrative, 10=dialog): Does the script's \
balance match? High narrative preference means rich descriptions; high \
dialog preference means character voices carry the story.
- Puzzle Complexity (1=minimal, 10=challenging): Are puzzles present \
and appropriately difficult? A low score means puzzles should be simple \
or absent; a high score means meaningful obstacles requiring thought.
- Levity (1=somber, 10=comedic): Does the tone match? Check humor \
frequency, dark themes, and overall emotional register.
- General Preferences: Does the script honor any specific requests in \
the player's free-text preferences?
- Player Prompt: If provided, does the script deliver the specific \
experience requested?

Evaluation Approach:
- Consider the script holistically—individual moments may vary from \
the overall preference balance.
- Weight the Player Prompt heavily if provided; it represents what \
they want right now.
- Be pragmatic: perfect alignment is impossible. Flag issues only \
when the mismatch would noticeably disappoint the player.

Output Format - Story Edit Report:
- If aligned: State "Script aligns well with player preferences. No \
significant adjustments needed."
- If misaligned: List each concern with:
  - Preference dimension affected
  - Current state in script
  - Player's preference/expectation
  - Specific examples from the script
  - Suggested direction for revision (not specific rewrites—that's \
the Scripter's job)"""


# ---------------------------------------------------------------------------
# ZWorld Format Description (injected with ZWorld input)
# ---------------------------------------------------------------------------

_ZWORLD_FORMAT_PROMPT = """\
The following describes the ZWorld format used in Z-Forge:

A ZWorld specification includes:
- id: a unique text identifier (e.g., "discworld")
- name: the display name (e.g., "Discworld")
- locations: nested list with id, name, description, and optional sublocations
- characters: each with id, names (with optional context), and history
- relationships: describing personal history and current relationship between \
two characters (by id)
- events: significant occurrences with descriptions and dates"""


# ---------------------------------------------------------------------------
# System Prompt Builders
# ---------------------------------------------------------------------------


def _build_author_system_prompt(state: ExperienceGenerationState) -> str:
    """Build the Author's system prompt from current state."""
    parts = [_AUTHOR_ROLE_PROMPT]

    # ZWorld format and data
    parts.append(f"\n\n{_ZWORLD_FORMAT_PROMPT}")
    parts.append(f"\n\nZWorld:\n{json.dumps(state['z_world'], indent=2)}")

    # Preferences
    parts.append(
        f"\n\nPlayer Preferences:\n{json.dumps(state['preferences'], indent=2)}"
    )

    # Player prompt
    if state.get("player_prompt"):
        parts.append(f"\n\nPlayer Prompt: {state['player_prompt']}")

    # Feedback from Scripter (if revising)
    if state.get("outline_notes"):
        parts.append(
            f"\n\nScripter's Outline Notes (feedback for revision):\n"
            f"{state['outline_notes']}"
        )

    # Script for review (if reviewing)
    if state.get("script") and state["status"] == "awaiting_author_review":
        parts.append(f"\n\nScript to review:\n{state['script']}")
        if state.get("outline"):
            parts.append(f"\n\nYour Outline:\n{state['outline']}")

    return "".join(parts)


def _build_scripter_system_prompt(
    state: ExperienceGenerationState,
    if_engine_connector: IfEngineConnector,
) -> str:
    """Build the Scripter's system prompt from current state."""
    parts = [_SCRIPTER_ROLE_PROMPT]

    # Engine context
    engine_name = if_engine_connector.get_engine_name()
    script_prompt = if_engine_connector.get_script_prompt()
    parts.append(f"\n\nIF Engine: {engine_name}")
    parts.append(f"\n\nEngine Script Prompt:\n{script_prompt}")

    # Outline and tech notes
    if state.get("outline"):
        parts.append(f"\n\nAuthor's Outline:\n{state['outline']}")
    if state.get("tech_notes"):
        parts.append(f"\n\nAuthor's Tech Notes:\n{state['tech_notes']}")

    # Preferences
    parts.append(
        f"\n\nPlayer Preferences:\n{json.dumps(state['preferences'], indent=2)}"
    )

    # Feedback
    if state.get("script_notes"):
        parts.append(
            f"\n\nAuthor's Script Notes (revision request):\n"
            f"{state['script_notes']}"
        )
    if state.get("tech_edit_report"):
        parts.append(
            f"\n\nTech Edit Report:\n{state['tech_edit_report']}"
        )
    if state.get("story_edit_report"):
        parts.append(
            f"\n\nStory Edit Report:\n{state['story_edit_report']}"
        )

    # Compiler errors
    if state.get("compiler_errors"):
        parts.append(
            "\n\nCompiler Errors from previous attempt:\n"
            + "\n".join(f"- {e}" for e in state["compiler_errors"])
        )

    # Previous script (for fixes/revisions)
    if state.get("script") and state["status"] in (
        "awaiting_script_fix",
        "awaiting_script_revision",
        "awaiting_tech_fix",
        "awaiting_story_fix",
    ):
        parts.append(f"\n\nPrevious Script:\n{state['script']}")

    return "".join(parts)


def _build_tech_editor_system_prompt(
    state: ExperienceGenerationState,
) -> str:
    """Build the Technical Editor's system prompt from current state."""
    parts = [_TECH_EDITOR_ROLE_PROMPT]

    if state.get("script"):
        parts.append(f"\n\nScript to review:\n{state['script']}")
    if state.get("tech_notes"):
        parts.append(
            f"\n\nAuthor's Tech Notes (intentional exceptions):\n"
            f"{state['tech_notes']}"
        )

    # Player's logical vs mood preference
    prefs = state.get("preferences", {})
    logical_vs_mood = prefs.get("logicalVsMood", 5)
    parts.append(
        f"\n\nPlayer's Logical vs. Mood preference: {logical_vs_mood}/10"
    )

    return "".join(parts)


def _build_story_editor_system_prompt(
    state: ExperienceGenerationState,
) -> str:
    """Build the Story Editor's system prompt from current state."""
    parts = [_STORY_EDITOR_ROLE_PROMPT]

    if state.get("script"):
        parts.append(f"\n\nScript to review:\n{state['script']}")

    parts.append(
        f"\n\nPlayer Preferences:\n{json.dumps(state['preferences'], indent=2)}"
    )

    if state.get("player_prompt"):
        parts.append(f"\n\nPlayer Prompt: {state['player_prompt']}")

    return "".join(parts)


# ---------------------------------------------------------------------------
# Action Prompts
# ---------------------------------------------------------------------------


def _get_action_prompt(status: str) -> str:
    """Return the HumanMessage action prompt for the current status."""
    _RATIONALE_SUFFIX = (
        "\n\nWhen calling your tool, include a concise `rationale` "
        "(1-3 sentences) explaining your reasoning or the key decisions you made."
    )
    prompts = {
        "awaiting_outline": (
            "Create a Story Outline and Tech Notes based on the provided inputs."
        ),
        "awaiting_outline_revision": (
            "Revise your Story Outline based on the Scripter's feedback."
        ),
        "awaiting_outline_review": (
            "Evaluate whether this Outline is suitable for scripting and "
            "aligned with player preferences."
        ),
        "awaiting_script": (
            "Write a complete script in the configured IF engine's language "
            "based on the approved Outline."
        ),
        "awaiting_script_fix": (
            "Fix the compiler errors in your script and resubmit."
        ),
        "awaiting_script_revision": (
            "Revise the script based on the Author's Script Notes."
        ),
        "awaiting_tech_fix": (
            "Fix the logical inconsistencies identified in the Tech Edit "
            "Report and resubmit the script."
        ),
        "awaiting_story_fix": (
            "Modify the script to better align with player preferences "
            "as described in the Story Edit Report."
        ),
        "awaiting_author_review": (
            "Review this Script against your Outline. Approve if it "
            "matches your vision, or provide Script Notes explaining "
            "what must change."
        ),
        "awaiting_tech_edit": (
            "Review this script for logical and spatial consistency."
        ),
        "awaiting_story_edit": (
            "Review this script for alignment with player preferences."
        ),
    }
    base = prompts.get(status, "Continue the process.")
    return base + _RATIONALE_SUFFIX


# ---------------------------------------------------------------------------
# Node Factories
# ---------------------------------------------------------------------------


def _make_author_node(llm_connector: LlmConnector, on_status_update=None):
    model = llm_connector.get_model()

    @log_node("author")
    def author_node(state: ExperienceGenerationState) -> dict:
        set_current_status(state["status"])
        pre_msg = {
            "awaiting_outline": "Author is drafting outline...",
            "awaiting_outline_revision": "Author is revising outline...",
            "awaiting_author_review": "Author is reviewing script...",
        }.get(state["status"], "Author is working...")
        if on_status_update:
            on_status_update(pre_msg)
        system_prompt = _build_author_system_prompt(state)
        action_prompt = _get_action_prompt(state["status"])

        if state["status"] == "awaiting_author_review":
            tools = [experience_author_approve_script, experience_author_reject_script]
        else:
            tools = [experience_author_submit_outline]

        log.debug("author_node: invoking LLM with tools=%r", [t.name for t in tools])
        response = model.bind_tools(tools).invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=action_prompt),
        ])
        log.info(
            "author_node: LLM responded — tool_calls=%r",
            [tc.get("name") for tc in (response.tool_calls or [])],
        )
        next_msg = {
            "awaiting_outline": "Author drafted outline — awaiting Scripter review...",
            "awaiting_outline_revision": "Author revised outline — awaiting Scripter review...",
            "awaiting_author_review": "Author reviewed script — processing decision...",
        }.get(state["status"], "Author is working...")
        return {"messages": [response], "status_message": next_msg}

    return author_node


def _make_scripter_node(
    llm_connector: LlmConnector,
    if_engine_connector: IfEngineConnector,
    on_status_update=None,
):
    model = llm_connector.get_model()

    @log_node("scripter")
    def scripter_node(state: ExperienceGenerationState) -> dict:
        set_current_status(state["status"])
        pre_msg = {
            "awaiting_outline_review": "Scripter is evaluating outline...",
            "awaiting_script": "Scripter is writing script...",
            "awaiting_script_fix": "Scripter is fixing compilation errors...",
            "awaiting_script_revision": "Scripter is revising script...",
            "awaiting_tech_fix": "Scripter is fixing technical issues...",
            "awaiting_story_fix": "Scripter is adjusting story balance...",
        }.get(state["status"], "Scripter is working...")
        if on_status_update:
            on_status_update(pre_msg)
        system_prompt = _build_scripter_system_prompt(state, if_engine_connector)
        action_prompt = _get_action_prompt(state["status"])

        if state["status"] == "awaiting_outline_review":
            tools = [
                experience_scripter_approve_outline,
                experience_scripter_reject_outline,
            ]
        else:
            tools = [experience_scripter_submit_script]

        log.debug("scripter_node: invoking LLM with tools=%r", [t.name for t in tools])
        response = model.bind_tools(tools).invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=action_prompt),
        ])
        log.info(
            "scripter_node: LLM responded — tool_calls=%r",
            [tc.get("name") for tc in (response.tool_calls or [])],
        )
        next_msg = {
            "awaiting_outline_review": "Scripter evaluated outline — processing decision...",
            "awaiting_script": "Scripter wrote script — compiling...",
            "awaiting_script_fix": "Scripter revised script — compiling...",
            "awaiting_script_revision": "Scripter revised script — compiling...",
            "awaiting_tech_fix": "Scripter fixed technical issues — compiling...",
            "awaiting_story_fix": "Scripter adjusted story — compiling...",
        }.get(state["status"], "Scripter is working...")
        return {"messages": [response], "status_message": next_msg}

    return scripter_node


def _make_tech_editor_node(llm_connector: LlmConnector, on_status_update=None):
    model = llm_connector.get_model()

    @log_node("tech_editor")
    def tech_editor_node(state: ExperienceGenerationState) -> dict:
        set_current_status(state["status"])
        if on_status_update:
            on_status_update("Technical Editor is reviewing script...")
        system_prompt = _build_tech_editor_system_prompt(state)
        action_prompt = _get_action_prompt(state["status"])
        tools = [experience_techeditor_approve, experience_techeditor_reject]
        log.debug("tech_editor_node: invoking LLM with tools=%r", [t.name for t in tools])
        response = model.bind_tools(tools).invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=action_prompt),
        ])
        log.info(
            "tech_editor_node: LLM responded — tool_calls=%r",
            [tc.get("name") for tc in (response.tool_calls or [])],
        )
        return {"messages": [response], "status_message": "Technical Editor reviewed script — processing decision..."}

    return tech_editor_node


def _make_story_editor_node(llm_connector: LlmConnector, on_status_update=None):
    model = llm_connector.get_model()

    @log_node("story_editor")
    def story_editor_node(state: ExperienceGenerationState) -> dict:
        set_current_status(state["status"])
        if on_status_update:
            on_status_update("Story Editor is reviewing script...")
        system_prompt = _build_story_editor_system_prompt(state)
        action_prompt = _get_action_prompt(state["status"])
        tools = [experience_storyeditor_approve, experience_storyeditor_reject]
        log.debug("story_editor_node: invoking LLM with tools=%r", [t.name for t in tools])
        response = model.bind_tools(tools).invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=action_prompt),
        ])
        log.info(
            "story_editor_node: LLM responded — tool_calls=%r",
            [tc.get("name") for tc in (response.tool_calls or [])],
        )
        return {"messages": [response], "status_message": "Story Editor reviewed script — processing decision..."}

    return story_editor_node


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def _route_after_tool(state: ExperienceGenerationState) -> str:
    """Route to the next node based on the current status."""
    log.info("_route_after_tool: status=%r", state.get("status"))
    routing = {
        "awaiting_outline": "author",
        "awaiting_outline_review": "scripter",
        "awaiting_outline_revision": "author",
        "awaiting_script": "scripter",
        "awaiting_script_fix": "scripter",
        "awaiting_author_review": "author",
        "awaiting_script_revision": "scripter",
        "awaiting_tech_edit": "tech_editor",
        "awaiting_tech_fix": "scripter",
        "awaiting_story_edit": "story_editor",
        "awaiting_story_fix": "scripter",
        "complete": "end",
        "failed": "end",
    }
    return routing.get(state["status"], "end")


# ---------------------------------------------------------------------------
# Graph Builder
# ---------------------------------------------------------------------------


def build_experience_generation_graph(
    llm_connector: LlmConnector,
    if_engine_connector: IfEngineConnector,
    on_status_update=None,
):
    """Build and compile the experience generation LangGraph StateGraph."""
    graph = StateGraph(ExperienceGenerationState)

    graph.add_node("author", _make_author_node(llm_connector, on_status_update))
    graph.add_node(
        "scripter", _make_scripter_node(llm_connector, if_engine_connector, on_status_update)
    )
    graph.add_node("tech_editor", _make_tech_editor_node(llm_connector, on_status_update))
    graph.add_node("story_editor", _make_story_editor_node(llm_connector, on_status_update))
    graph.add_node("tools", ToolNode(all_experience_tools))

    graph.set_entry_point("author")
    graph.add_edge("author", "tools")
    graph.add_edge("scripter", "tools")
    graph.add_edge("tech_editor", "tools")
    graph.add_edge("story_editor", "tools")
    graph.add_conditional_edges("tools", _route_after_tool, {
        "author": "author",
        "scripter": "scripter",
        "tech_editor": "tech_editor",
        "story_editor": "story_editor",
        "end": END,
    })

    return graph.compile()
