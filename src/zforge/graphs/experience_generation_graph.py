"""LangGraph experience generation graph.

Twelve-node pipeline per docs/Experience Generation.md:

1.  outline_author — produces outline; may emit research_request
2.  outline_researcher — agentic RAG; fulfils outline research requests
3.  outline_reviewer — dual review (Tech Editor + Story Editor); PASS/FAIL
4.  arbiter_outline — overrules Story Editor when rejection stems from player premise
5.  prose_writer — expands outline into prose; may emit research_request
6.  prose_researcher — agentic RAG; fulfils prose research requests
7.  prose_reviewer — dual review; PASS/FAIL
8.  arbiter_prose — same as arbiter_outline but for prose stage
9.  ink_scripter — translates prose draft into Ink script
10. ink_compile_check — non-LLM; invokes IfEngineConnector.build()
11. ink_debugger — multi-mode repair node: fixes Ink compiler errors (mode=ink) or
    malformed JSON LLM responses (mode=json); destination node stored in state
12. ink_qa — virtual playtest for pathing errors
13. ink_auditor — final structural audit

Tool calls are executed inline within researcher nodes — outline_author and
prose_writer delegate research to dedicated researcher nodes rather than
running their own tool loops.

Implements: src/zforge/graphs/experience_generation_graph.py per
docs/Experience Generation.md.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph

from zforge.graphs.graph_utils import (
    ALLOWED_NODES,
    extract_text_content,
    log_node,
    make_world_query_tools,
)
from zforge.graphs.state import ExperienceGenerationState

# Pre-computed string for injecting into LLM prompts at module load time.
_ENTITY_TYPES = ", ".join(ALLOWED_NODES)

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from zforge.services.embedding.embedding_connector import EmbeddingConnector
    from zforge.services.if_engine.if_engine_connector import IfEngineConnector
    from zforge.services.llm.llm_connector import LlmConnector

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_REVIEW_ITERATIONS = 5
MAX_COMPILE_FIX_ITERATIONS = 3
MAX_SCRIPT_REWRITE_ITERATIONS = 5
MAX_RESEARCH_CALL_ITERATIONS = 8

# ---------------------------------------------------------------------------
# Agent Prompts (from docs/Experience Generation.md § Agent Role & Prompt
# Specifications)
# ---------------------------------------------------------------------------

_OUTLINE_AUTHOR_PROMPT = f"""\
You are a Lead Narrative Designer. Convert world data and player intent into \
a structural "beat sheet."

If you need additional world data before writing the outline, output ONLY a \
JSON object with key "research_request" containing your focused question(s) \
for the research assistant. You may do this up to the budget shown in the \
message; each time you will receive updated Research Notes.

IMPORTANT: The research assistant can only answer factual questions about the \
world — who characters are, what abilities they have, how factions relate, \
where locations are, what events have occurred in canon. It cannot make \
creative decisions for you. You are responsible for inventing the specific \
events, threats, motivations, consequences, and timeline placement of the \
story. If the player prompt says "Alice secretly saves Bob's life," it is \
YOUR job to decide what the threat is, why Alice intervenes, and how — \
informed by the world data you gather about those characters.
Good research requests: "Who is Alice?", "What abilities does Alice have?", \
"What factions threaten Bob's people?", "What relationship exists between \
Alice and Bob?"
Bad research requests: "What should the threat to Bob be?", "Why would \
Alice want to save him?"

Once you have sufficient context, produce the final output as ONLY a JSON \
object (no markdown fencing) with exactly these keys:
- "experience_title": a short, evocative title for this experience
- "outline": Structured Markdown of scenes and branching points \
(using === knot_names ===). The outline should total approximately 5-10% of \
the target prose word count from player preferences. The number of \
=== knot === sections must equal the target complexity (knot count) from \
player preferences exactly. Valid entity_type values for any world queries \
performed by the researcher are: {_ENTITY_TYPES}.
- "research_notes": an updated consolidated bulleted list of all factual \
world data gathered.

Adhere to all player preference scales (1-10): character/plot, \
narrative/dialog, levity, logical vs. mood, and puzzle complexity."""

_TECH_EDITOR_PROMPT = """\
You are the Logic Police. Your focus is the internal consistency of the \
story being built.
CRITICAL RULE: The player prompt establishes the founding premise of this \
experience. Do NOT penalise character relationships, motivations, or \
scenarios that follow directly from the player's stated premise, even if \
they seem unusual or contrary to established canon. Accept the premise as \
given and evaluate consistency within it.
1. Plot Holes: Ensure actions have clear motivations and that the player \
can't bypass critical story beats.
2. Branching Value: Ensure choices are meaningful and don't immediately \
"fold" back to the same result.
3. Pacing: Check if the sequence of events feels earned.
4. Output: respond with ONLY a JSON object (no markdown fencing) with \
exactly these keys: "status" (either "PASS" or "FAIL") and "feedback" \
(notes on plot logic)."""

_STORY_EDITOR_PROMPT = f"""\
You are the Lore Police. Your focus is the external consistency between \
the draft and the Z-World metadata.

CRITICAL RULE: The player prompt establishes the creative premise of this \
experience and may intentionally diverge from established world canon \
(e.g., an alternate-universe scenario where normally hostile factions are \
friendly, or a playful crossover). Do NOT flag the player's stated premise \
itself as a lore violation. Treat it as an accepted given. Your job is to \
ensure that the Z-World details referenced within the draft \
(entity names, traits, locations, world mechanics) are accurately \
represented once the premise is in play.

1. Lore Adherence: Using the Research Notes provided, ensure world facts \
are used accurately (e.g., if world.tech_level: medieval, flag any mention \
of steam engines unrelated to the premise).
2. Fact-Checking: Cross-reference mentions of NPCs, artifacts, or \
locations against the research notes and world metadata provided.
3. Tone: Ensure the draft matches the "voice" established in the world \
metadata.
4. Output: respond with ONLY a JSON object (no markdown fencing) with \
exactly these keys: "status" (either "PASS" or "FAIL") and "feedback" \
(notes on Z-World violations)."""

_PROSE_WRITER_PROMPT = f"""\
You are a Professional Fiction Author writing INTERACTIVE FICTION, not a \
traditional linear narrative. You are writing prose that will be translated \
into an Ink script with real player choices and branching paths.

If you need additional world data (sensory details, character traits, \
relationships), output ONLY a JSON object with key "research_request" \
containing your focused question(s) for the research assistant. You may \
do this up to the budget shown in the message; each time you will receive \
updated Research Notes. Valid entity_type values for any world queries are: \
{_ENTITY_TYPES}.

Once you have sufficient context, write the full prose draft as plain text \
(no JSON wrapper). Follow these rules exactly:

1. STRUCTURE: Follow the outline scene by scene. Use the === knot_name === \
markers from the outline as section headers in your prose draft so each \
section of prose maps directly to a knot.

2. BRANCHING IS MANDATORY: At every choice point defined in the outline, \
you MUST write the full prose for EVERY branch — not just a label. Each \
branch is a separate section of narrative text that the player will \
experience exclusively. Mutually exclusive paths must all be written in \
full. A draft with only one thread of narrative is incomplete.

3. CHOICE PRESENTATION: Introduce each choice with the player's options \
listed as: + [Choice Text]. Then, on a new section beneath each option, \
write the prose that follows from that choice.

4. Target the total word count specified in player preferences, distributed \
across all branches.

5. Respect all player preference scales (character/plot, narrative/dialog, \
levity, logical vs. mood, puzzle complexity) and any editor feedback \
provided."""

_RESEARCHER_PROMPT = f"""\
You are a Research Assistant with access to the Z-World hybrid data store.

You have received a research request from a creative agent. Your task is:

1. Use the retrieval tools to gather all data relevant to the request. \
Understand what each tool is for:
   - query_entities: Look up specific entities (characters, locations, \
factions, etc.) by name or description. Returns a synthesized summary plus \
graph relationships. Best for: "Who is Alice?", "What is the Northern Kingdom?"
   - retrieve_source: Search the original source text for relevant passages. \
Returns verbatim chunks. Best for: topical questions, world mechanics, \
environmental details, specific quotes, or anything spread across the source \
rather than captured in a single entity summary.
   - find_relationship_by_name: Find how two named entities are connected in \
the world graph. Best for: "What is the relationship between Alice and Bob?"
   - list_entities: Get a catalog of all entities of a type. Best for building \
a roster: "Who are all the characters?", "What locations exist?"
   - get_neighbors: Get all graph connections from a known entity ID (returned \
by query_entities). More surgical follow-up after an initial entity lookup.
   - get_source_passages: Get raw source text mentioning a known entity ID. \
Cheaper than retrieve_source when the entity is already identified.
   - find_relationship / find_path: For known entity IDs — direct and indirect \
graph connections.
   The valid entity_type values for query_entities are: {_ENTITY_TYPES}. \
Do not query for any other entity type. Guidance on less-obvious types: \
use entity_type="time_period" (or list_entities(entity_type="time_period")) \
for questions about when events occur; use entity_type="concept" or \
entity_type="belief_system" for questions about magic systems, prophecy \
mechanics, or world rules; use retrieve_source with keyword-rich queries \
for thematic questions that are not tied to a single named entity.
   If the request contains multiple questions, make a SEPARATE tool call for \
each one before synthesizing your results — do not try to answer all \
questions with a single broad tool call. Break broad questions into specific \
lookups. For example, "What threats face Bob's people?" should become a \
query_entities call for Bob's faction plus a retrieve_source call for threats \
or enemies of that faction.

   BE PERSISTENT: If query_entities returns "No matching entities found", do \
NOT give up. Try a different tool or a different search query. Specifically, \
if query_entities fails to find a character or location by name, use \
retrieve_source with broader keywords to find relevant passages in the \
source text. Your goal is to find information, not to report that you \
couldn't find it on your first try.
2. Combine the retrieved data with the existing Research Notes provided, \
avoiding duplication.
3. Return ONLY a JSON object (no markdown fencing) with exactly this key: \
- "research_notes": the updated consolidated bulleted list of factual \
world data. If no information was found after all attempts, explain \
briefly what you tried and what was missing."""

_INK_SCRIPTER_PROMPT = """\
You are a Narrative Implementation Engineer. Translate the prose draft \
into valid Ink syntax.
1. Use === knots ===, + choices, and -> diverts.
2. Implement state variables as requested in the draft.
3. Ensure all paths lead to a valid -> END.
4. Every choice block must contain at least two options. A block with \
only one choice is not a real decision — either remove it and use a \
divert directly, or split the content into genuine alternatives.

Produce the complete Ink script as your response — nothing else."""

_INK_DEBUGGER_PROMPT = """\
You are a Senior Game Developer. Fix a broken Ink script based on \
compiler error logs.
1. Fix syntax errors and break infinite loops.
2. Return the functional script without altering the author's prose style.

Produce the complete fixed Ink script as your response — nothing else."""

_JSON_DEBUGGER_PROMPT = """\
You are a JSON Repair Specialist. The text below is a malformed or \
improperly-formatted LLM response that was supposed to be a valid JSON object. \
Extract and return the intended JSON object, fixing any syntax errors, \
escaped characters, or extraneous markdown.
Return ONLY the valid JSON object — no markdown fencing, no explanation."""

_INK_QA_PROMPT = """\
You are a Game QA Lead. Perform a "Virtual Playtest" of the final Ink \
script.
1. Pathing: Ensure all knots are reachable.
2. Dead Ends: Flag any path that terminates without a proper -> END.
3. Flow: Identify areas where the player might get "stuck" in a choice \
cycle.
4. False Choices: Flag any choice block that contains only a single \
option — this is not a real decision and must be revised.

Respond with ONLY a JSON object (no markdown fencing) with exactly these \
keys: "status" (either "PASS" or "FAIL") and "feedback" (notes on \
pathing/flow issues)."""

_INK_AUDITOR_PROMPT = """\
You are the Lead Script Auditor. Perform a final high-level technical \
check on the Ink Script.
1. Variable Integrity: Ensure variables are initialized before being \
checked.
2. State Logic: Verify that flag-setting is placed logically relative \
to diverts.
3. Structural Polish: Check for "sticky" choices or nested logic traps \
specific to Ink.

Respond with ONLY a JSON object (no markdown fencing) with exactly these \
keys: "status" (either "PASS" or "FAIL") and "feedback" (notes on \
structural issues)."""

_ARBITER_PROMPT = """\
You are a Senior Creative Director arbitrating a dispute between the \
Story Editor (Lore Police) and the player.

The player has submitted a premise for their interactive experience. \
The Story Editor reviewed the draft and rejected it with a lore concern. \
Your task is to determine whether the Story Editor's rejection is \
primarily targeting the player's stated premise itself — i.e., the editor \
is penalising a creative divergence the player deliberately introduced — \
rather than a genuine error in the draft's execution of world facts.

Rules:
- If the Story Editor's rejection is caused by, or flows directly from, \
the player's premise (e.g., the editor flags a faction alignment, \
relationship, or scenario that the player explicitly set up), \
choose OVERRULE.
- If the rejection is caused by the writer misrepresenting world facts \
that are not covered or implied by the player's premise, choose UPHOLD.

Respond with ONLY a JSON object (no markdown fencing) with exactly \
these keys:
- "verdict": either "OVERRULE" or "UPHOLD"
- "reason": a one-sentence explanation"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(title: str) -> str:
    """Convert a title to a kebab-case slug."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def _first_sentence(text: str, max_len: int = 120) -> str:
    """Return the first sentence of *text*, truncated to *max_len* chars."""
    if not text:
        return ""
    sentence = text.strip().split(".")[0].strip()
    return sentence[:max_len]


def _parse_json_response(content: str) -> dict[str, Any] | None:
    """Extract a JSON object from an LLM response, tolerating markdown fencing."""
    text = content.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            pass
    return None


# ---------------------------------------------------------------------------
# Node Factories
# ---------------------------------------------------------------------------


def _make_outline_author_node(
    llm_connector: LlmConnector,
    model_name: str | None = None,
):
    """Produces outline, research notes, and experience title.

    No longer runs its own tool loop — emits a ``research_request`` when it
    needs additional world data, which the researcher node fulfils.
    """

    _model_cache: list[Any] = []

    @log_node("outline_author")
    async def outline_author_node(state: ExperienceGenerationState) -> dict[str, Any]:
        # If the debugger has provided a repaired JSON response, parse it directly.
        if state.get("debugger_input") is not None:
            parsed = _parse_json_response(state["debugger_input"] or "")
            clear_debugger: dict[str, Any] = {
                "debugger_input": None,
                "debugger_return_node": None,
                "last_step_rationale": None,
                "action_log": [],
                "outline_review_count": 0,
                "prose_review_count": 0,
                "compile_fix_count": 0,
                "script_rewrite_count": 0,
            }
            if not parsed:
                log.warning("outline_author: debugger-fixed JSON still unparseable — failing")
                return {
                    **clear_debugger,
                    "status": "failed",
                    "failure_reason": "Debugger could not produce valid JSON for outline",
                    "status_message": "Experience generation failed: outline JSON could not be repaired",
                }
            title = parsed.get("experience_title", "Untitled Experience")
            return {
                **clear_debugger,
                "outline": parsed.get("outline", ""),
                "research_notes": parsed.get("research_notes", ""),
                "experience_title": title,
                "experience_slug": _slugify(title),
                "outline_feedback": None,
                "status": "reviewing_outline",
                "status_message": f"Outline '{title}' drafted (repaired); under review...",
            }

        if not _model_cache:
            _model_cache.append(llm_connector.get_model(model_name))
        model = _model_cache[0]

        # Build messages
        world_context = json.dumps(state.get("zworld_kvp") or {}, indent=2)
        prefs_context = json.dumps(state["preferences"], indent=2)
        human_parts = [
            f"World metadata:\n{world_context}",
            f"\nPlayer preferences:\n{prefs_context}",
            f"\nPlayer request: {state['player_prompt']}",
        ]
        if state.get("research_notes"):
            human_parts.append(
                f"\nResearch Notes (gathered so far):\n{state['research_notes']}"
            )
        if state.get("outline_feedback"):
            human_parts.append(
                f"\nThe reviewers rejected your previous outline with this "
                f"feedback. Revise accordingly:\n{state['outline_feedback']}"
            )
        research_remaining = MAX_RESEARCH_CALL_ITERATIONS - state.get("research_call_count", 0)
        human_parts.append(f"\nResearch calls remaining: {research_remaining}")
        if research_remaining <= 0:
            human_parts.append(
                "\nRESEARCH LIMIT REACHED: You must produce your final JSON output now "
                "using only the information already available. Do NOT output a research_request."
            )

        messages: list[BaseMessage] = [
            SystemMessage(content=_OUTLINE_AUTHOR_PROMPT),
            HumanMessage(content="\n".join(human_parts)),
        ]

        response = await model.ainvoke(messages)
        messages.append(response)
        content = extract_text_content(getattr(response, "content", ""))
        parsed = _parse_json_response(content)

        if not parsed:
            log.warning(
                "outline_author: could not parse JSON — routing to debugger; preview: %r",
                content[:300],
            )
            return {
                "status": "debugging",
                "status_message": "Outline author produced invalid JSON; routing to debugger...",
                "debugger_mode": "json",
                "debugger_return_node": "outline_author",
                "debugger_input": content,
                "last_step_rationale": None,
                "action_log": [],
                "outline_review_count": 0,
                "prose_review_count": 0,
                "compile_fix_count": 0,
                "script_rewrite_count": 0,
                "messages": messages,
            }

        # If the author is requesting research, check budget then route or force completion
        if "research_request" in parsed:
            _rq = parsed["research_request"]
            if state.get("research_call_count", 0) < MAX_RESEARCH_CALL_ITERATIONS:
                return {
                    "research_request": _rq,
                    "research_caller": "outline_author",
                    "research_call_count": 1,
                    "status": "researching_outline",
                    "status_message": "Outliner requesting research...",
                    "last_step_rationale": f"Research needed: {_rq}",
                    "action_log": [],
                    "outline_review_count": 0,
                    "prose_review_count": 0,
                    "compile_fix_count": 0,
                    "script_rewrite_count": 0,
                    "messages": messages,
                }
            # Budget exhausted — force the model to produce its final output now
            log.warning(
                "outline_author: research call limit (%d) reached; forcing final output",
                MAX_RESEARCH_CALL_ITERATIONS,
            )
            messages.append(HumanMessage(
                content=(
                    f"Research limit of {MAX_RESEARCH_CALL_ITERATIONS} calls reached. "
                    "You must produce your final JSON output now using only the "
                    "information you already have."
                )
            ))
            response = await model.ainvoke(messages)
            messages.append(response)
            content = extract_text_content(getattr(response, "content", ""))
            parsed = _parse_json_response(content)
            if not parsed:
                return {
                    "status": "debugging",
                    "status_message": "Outline author produced invalid JSON after research limit; routing to debugger...",
                    "debugger_mode": "json",
                    "debugger_return_node": "outline_author",
                    "debugger_input": content,
                    "last_step_rationale": None,
                    "action_log": [],
                    "outline_review_count": 0,
                    "prose_review_count": 0,
                    "compile_fix_count": 0,
                    "script_rewrite_count": 0,
                    "messages": messages,
                }

        title = parsed.get("experience_title", "Untitled Experience")
        return {
            "outline": parsed.get("outline", ""),
            "research_notes": parsed.get("research_notes", ""),
            "experience_title": title,
            "experience_slug": _slugify(title),
            "outline_feedback": None,
            "status": "reviewing_outline",
            "status_message": f"Outline '{title}' drafted; under review...",
            "last_step_rationale": None,
            "action_log": [],
            "outline_review_count": 0,
            "prose_review_count": 0,
            "compile_fix_count": 0,
            "script_rewrite_count": 0,
            "messages": messages,
        }

    return outline_author_node


def _make_dual_reviewer_node(
    llm_connector: LlmConnector,
    model_name: str | None,
    node_name: str,
    artifact_key: str,
    feedback_key: str,
    counter_key: str,
    pass_status: str,
    fail_status: str,
    story_rejected_status: str,
    pass_message: str,
    fail_message: str,
):
    """Factory for dual-review nodes (Tech Editor + Story Editor).

    Used by both outline_reviewer and prose_reviewer.  The Story Editor now
    relies on pre-gathered research_notes rather than its own retrieval tools.
    """
    _model_cache: list[Any] = []

    @log_node(node_name)
    async def reviewer_node(state: ExperienceGenerationState) -> dict[str, Any]:
        if not _model_cache:
            _model_cache.append(llm_connector.get_model(model_name))
        model = _model_cache[0]

        artifact = state.get(artifact_key, "") or ""
        world_context = json.dumps(state.get("zworld_kvp") or {}, indent=2)

        human_content = (
            f"World metadata:\n{world_context}\n\n"
            f"Draft to review:\n{artifact}"
        )

        # Tech Editor review (no tools — structural review only)
        tech_messages = [
            SystemMessage(content=_TECH_EDITOR_PROMPT),
            HumanMessage(content=human_content),
        ]
        tech_response = await model.ainvoke(tech_messages)
        tech_content = extract_text_content(getattr(tech_response, "content", ""))
        tech_result = _parse_json_response(tech_content) or {"status": "PASS", "feedback": ""}

        # Story Editor review (single call with research_notes — no tool loop)
        research_notes = state.get("research_notes") or ""
        story_human_content = (
            f"World metadata:\n{world_context}\n\n"
            f"Research Notes:\n{research_notes}\n\n"
            f"Draft to review:\n{artifact}"
        )
        story_messages: list[BaseMessage] = [
            SystemMessage(content=_STORY_EDITOR_PROMPT),
            HumanMessage(content=story_human_content),
        ]
        story_response = await model.ainvoke(story_messages)
        story_content = extract_text_content(getattr(story_response, "content", ""))
        story_result = _parse_json_response(story_content) or {"status": "PASS", "feedback": ""}

        tech_pass = tech_result.get("status", "").upper() == "PASS"
        story_pass = story_result.get("status", "").upper() == "PASS"
        both_pass = tech_pass and story_pass

        log.info(
            "%s: tech=%s story=%s",
            node_name,
            "PASS" if tech_pass else "FAIL",
            "PASS" if story_pass else "FAIL",
        )

        zero_counters = {
            "outline_review_count": 0,
            "prose_review_count": 0,
            "compile_fix_count": 0,
            "script_rewrite_count": 0,
        }

        if both_pass:
            rationale = f"{node_name}: Both editors approved — logic sound and lore consistent."
            return {
                **zero_counters,
                "story_editor_feedback": None,
                "tech_editor_feedback": None,
                "status": pass_status,
                "status_message": pass_message,
                "last_step_rationale": rationale,
                "action_log": [],
            }

        tech_fb = tech_result.get("feedback", "")
        story_fb = story_result.get("feedback", "")

        # Build combined feedback (used if arbiter upholds or only tech failed)
        feedback_parts = []
        if not tech_pass:
            feedback_parts.append(f"[Technical Editor] {tech_fb}")
        if not story_pass:
            feedback_parts.append(f"[Story Editor] {story_fb}")
        combined_feedback = "\n\n".join(feedback_parts)

        if not story_pass:
            # Route to Arbiter regardless of whether Tech Editor also failed.
            # Arbiter determines if Story Editor rejection is premise-based.
            if not tech_pass and not story_pass:
                rationale = (
                    f"{node_name}: Both editors rejected — sending to Arbiter; "
                    f"tech: {_first_sentence(tech_fb)}; lore: {_first_sentence(story_fb)}."
                )
            else:
                rationale = (
                    f"{node_name}: Story Editor rejected — sending to Arbiter; "
                    f"{_first_sentence(story_fb)}."
                )
            return {
                **zero_counters,
                # No counter increment yet — Arbiter will increment if it upholds.
                feedback_key: combined_feedback,
                "story_editor_feedback": story_fb,
                "tech_editor_feedback": tech_fb if not tech_pass else None,
                "status": story_rejected_status,
                "status_message": "Story Editor rejected — sending to Arbiter...",
                "last_step_rationale": rationale,
                "action_log": [],
            }

        # Only Tech Editor failed — normal revision loop, no Arbiter needed.
        rationale = f"{node_name}: Technical Editor rejected — {_first_sentence(tech_fb)}."
        return {
            **zero_counters,
            counter_key: 1,
            feedback_key: f"[Technical Editor] {tech_fb}",
            "story_editor_feedback": None,
            "tech_editor_feedback": tech_fb,
            "status": fail_status,
            "status_message": fail_message,
            "last_step_rationale": rationale,
            "action_log": [],
        }

    return reviewer_node


def _make_arbiter_node(
    llm_connector: LlmConnector,
    model_name: str | None,
    node_name: str,
    feedback_key: str,
    counter_key: str,
    pass_status: str,
    fail_status: str,
    pass_message: str,
    fail_message: str,
):
    """Arbiter node: overrules Story Editor when its rejection stems from the player's premise.

    Receives only the player prompt and the Story Editor's rejection reason.
    Does not see the outline/prose draft.  If the verdict is OVERRULE and the
    Tech Editor had also failed, the revision loop continues with only the tech
    feedback visible to the writer.
    """
    _model_cache: list[Any] = []

    @log_node(node_name)
    async def arbiter_node(state: ExperienceGenerationState) -> dict[str, Any]:
        if not _model_cache:
            _model_cache.append(llm_connector.get_model(model_name))
        model = _model_cache[0]

        player_prompt = state["player_prompt"]
        story_feedback = state.get("story_editor_feedback") or ""

        messages = [
            SystemMessage(content=_ARBITER_PROMPT),
            HumanMessage(
                content=(
                    f"Player premise:\n{player_prompt}\n\n"
                    f"Story Editor rejection reason:\n{story_feedback}"
                )
            ),
        ]

        response = await model.ainvoke(messages)
        content = extract_text_content(getattr(response, "content", ""))
        result = _parse_json_response(content) or {"verdict": "UPHOLD", "reason": ""}

        verdict = result.get("verdict", "UPHOLD").upper()
        reason = result.get("reason", "")
        tech_feedback = state.get("tech_editor_feedback")

        log.info("%s: verdict=%s reason=%r", node_name, verdict, reason)

        zero_counters = {
            "outline_review_count": 0,
            "prose_review_count": 0,
            "compile_fix_count": 0,
            "script_rewrite_count": 0,
        }

        if verdict == "OVERRULE":
            if tech_feedback:
                # Story Editor overruled, but Tech Editor still failed — continue
                # the revision loop with only the tech feedback visible.
                rationale = (
                    f"{node_name}: Story Editor overruled — {reason}. "
                    f"Tech Editor rejection stands; revising."
                )
                return {
                    **zero_counters,
                    counter_key: 1,
                    feedback_key: f"[Technical Editor] {tech_feedback}",
                    "story_editor_feedback": None,
                    "tech_editor_feedback": None,
                    "status": fail_status,
                    "status_message": fail_message,
                    "last_step_rationale": rationale,
                    "action_log": [],
                }
            # Story Editor overruled and Tech Editor had also passed → continue.
            rationale = f"{node_name}: Story Editor overruled — {reason}. Proceeding."
            return {
                **zero_counters,
                "story_editor_feedback": None,
                "tech_editor_feedback": None,
                "status": pass_status,
                "status_message": pass_message,
                "last_step_rationale": rationale,
                "action_log": [],
            }

        # UPHOLD — Story Editor rejection stands; revision loop with combined feedback.
        rationale = f"{node_name}: Story Editor upheld — {reason}. Revising."
        return {
            **zero_counters,
            counter_key: 1,
            "story_editor_feedback": None,
            "tech_editor_feedback": None,
            "status": fail_status,
            "status_message": fail_message,
            "last_step_rationale": rationale,
            "action_log": [],
        }

    return arbiter_node


def _make_prose_writer_node(
    llm_connector: LlmConnector,
    model_name: str | None = None,
):
    """Expands outline into vivid prose draft.

    No longer runs its own tool loop — emits a ``research_request`` when it
    needs additional world data, which the researcher node fulfils.
    """

    _model_cache: list[Any] = []

    @log_node("prose_writer")
    async def prose_writer_node(state: ExperienceGenerationState) -> dict[str, Any]:
        if not _model_cache:
            _model_cache.append(llm_connector.get_model(model_name))
        model = _model_cache[0]

        prefs_context = json.dumps(state["preferences"], indent=2)
        human_parts = [
            f"Outline:\n{state.get('outline', '')}",
            f"\nResearch Notes:\n{state.get('research_notes', '')}",
            f"\nPlayer preferences:\n{prefs_context}",
        ]
        if state.get("prose_feedback"):
            human_parts.append(
                f"\nThe reviewers rejected your previous draft with this "
                f"feedback. Revise accordingly:\n{state['prose_feedback']}"
            )
        research_remaining = MAX_RESEARCH_CALL_ITERATIONS - state.get("research_call_count", 0)
        human_parts.append(f"\nResearch calls remaining: {research_remaining}")
        if research_remaining <= 0:
            human_parts.append(
                "\nRESEARCH LIMIT REACHED: You must write the full prose draft now "
                "using only the information already available. Do NOT output a research_request."
            )

        messages: list[BaseMessage] = [
            SystemMessage(content=_PROSE_WRITER_PROMPT),
            HumanMessage(content="\n".join(human_parts)),
        ]

        response = await model.ainvoke(messages)
        messages.append(response)
        content = extract_text_content(getattr(response, "content", ""))

        # Check if the writer is requesting research (budget-gated)
        parsed = _parse_json_response(content)
        if parsed and "research_request" in parsed:
            _rq = parsed["research_request"]
            if state.get("research_call_count", 0) < MAX_RESEARCH_CALL_ITERATIONS:
                return {
                    "research_request": _rq,
                    "research_caller": "prose_writer",
                    "research_call_count": 1,
                    "status": "researching_prose",
                    "status_message": "Writer requesting research...",
                    "last_step_rationale": f"Research needed: {_rq}",
                    "action_log": [],
                    "outline_review_count": 0,
                    "prose_review_count": 0,
                    "compile_fix_count": 0,
                    "script_rewrite_count": 0,
                    "messages": messages,
                }
            # Budget exhausted — force the model to write the prose draft
            log.warning(
                "prose_writer: research call limit (%d) reached; forcing prose output",
                MAX_RESEARCH_CALL_ITERATIONS,
            )
            messages.append(HumanMessage(
                content=(
                    f"Research limit of {MAX_RESEARCH_CALL_ITERATIONS} calls reached. "
                    "You must write the full prose draft now using only the "
                    "information you already have."
                )
            ))
            response = await model.ainvoke(messages)
            messages.append(response)
            content = extract_text_content(getattr(response, "content", ""))

        # Otherwise the response is the prose draft (plain text)
        return {
            "prose_draft": content,
            "prose_feedback": None,
            "status": "reviewing_prose",
            "status_message": "Prose draft written; under review...",
            "last_step_rationale": None,
            "action_log": [],
            "outline_review_count": 0,
            "prose_review_count": 0,
            "compile_fix_count": 0,
            "script_rewrite_count": 0,
            "messages": messages,
        }

    return prose_writer_node


def _make_researcher_node(
    llm_connector: LlmConnector,
    embedding_connector: EmbeddingConnector,
    node_name: str,
    model_name: str | None = None,
):
    """Agentic RAG node: fulfils a research_request and updates research_notes."""

    _model_cache: list[Any] = []

    @log_node(node_name)
    async def researcher_node(state: ExperienceGenerationState) -> dict[str, Any]:
        if not _model_cache:
            _model_cache.append(llm_connector.get_model(model_name))
        model = _model_cache[0]

        z_bundle_root = state.get("z_bundle_root")
        tools: list[Any] = []
        if z_bundle_root is not None:
            (
                query_entities, retrieve_source, find_relationship,
                find_relationship_by_name, list_entities, get_neighbors,
                find_path, get_source_passages,
            ) = make_world_query_tools(
                z_bundle_root, ALLOWED_NODES, embedding_connector
            )
            tools = [
                query_entities, retrieve_source, find_relationship,
                find_relationship_by_name, list_entities, get_neighbors,
                find_path, get_source_passages,
            ]

        request = state.get("research_request") or ""
        existing_notes = state.get("research_notes") or ""
        zworld_kvp = state.get("zworld_kvp") or {}
        world_title = zworld_kvp.get("title", "Unknown World")
        world_summary = zworld_kvp.get("summary", "No summary available.")

        messages: list[BaseMessage] = [
            SystemMessage(content=_RESEARCHER_PROMPT),
            HumanMessage(
                content=(
                    f"You are researching for the world: {world_title}\n"
                    f"World Summary: {world_summary}\n\n"
                    f"Existing Research Notes:\n{existing_notes}\n\n"
                    f"Research Request:\n{request}"
                )
            ),
        ]

        bound_model = model.bind_tools(tools) if tools else model
        tool_map = {t.name: t for t in tools}
        tool_calls_log: list[dict[str, Any]] = []

        while True:
            response = await bound_model.ainvoke(messages)
            messages.append(response)

            if not (hasattr(response, "tool_calls") and response.tool_calls):
                break

            for tc in response.tool_calls:
                tool_fn = tool_map.get(tc["name"])
                if tool_fn:
                    result = await tool_fn.ainvoke(tc["args"])
                    log.info(
                        "%s: tool %s args=%r returned %d chars",
                        node_name,
                        tc["name"],
                        tc["args"],
                        len(str(result)),
                    )
                    tool_calls_log.append({
                        "type": "tool_call",
                        "node": node_name,
                        "role": "researcher",
                        "tool": tc["name"],
                        "args": tc["args"],
                    })
                    messages.append(
                        ToolMessage(
                            content=str(result),
                            tool_call_id=tc["id"],
                            name=tc["name"],
                        )
                    )

        content = extract_text_content(getattr(response, "content", ""))
        parsed = _parse_json_response(content)
        if not parsed:
            # If JSON parsing fails, treat the entire content as the updated notes.
            # This is a safe fallback since the prompt explicitly asks for consolidation.
            parsed = {"research_notes": content.strip() or existing_notes}
            log.warning(
                "researcher_node: failed to parse JSON from final response (using raw content as notes). Preview: %r",
                content[:100],
            )
        updated_notes = parsed.get("research_notes", existing_notes)

        if not updated_notes:
            # If still empty, explicitly mark it as "No notes found" so the author
            # stops looping forever, and so it shows up in debug artifacts.
            updated_notes = f"[System] Research complete but no notes were generated. Request was: {request}"

        return {
            "research_notes": updated_notes,
            "research_request": None,
            "research_caller": None,
            "action_log": tool_calls_log,
            "outline_review_count": 0,
            "prose_review_count": 0,
            "compile_fix_count": 0,
            "script_rewrite_count": 0,
        }

    return researcher_node


def _make_ink_scripter_node(
    llm_connector: LlmConnector,
    model_name: str | None = None,
):
    """Translates prose draft into Ink script."""
    _model_cache: list[Any] = []

    @log_node("ink_scripter")
    async def ink_scripter_node(state: ExperienceGenerationState) -> dict[str, Any]:
        if not _model_cache:
            _model_cache.append(llm_connector.get_model(model_name))
        model = _model_cache[0]

        human_parts = [f"Prose draft to convert to Ink:\n{state.get('prose_draft', '')}"]
        if state.get("qa_feedback"):
            human_parts.append(
                f"\nThe QA analyst found these pathing issues in the previous "
                f"script. Fix them in this rewrite:\n{state['qa_feedback']}"
            )
        if state.get("audit_feedback"):
            human_parts.append(
                f"\nThe auditor found these structural issues in the previous "
                f"script. Fix them in this rewrite:\n{state['audit_feedback']}"
            )

        messages = [
            SystemMessage(content=_INK_SCRIPTER_PROMPT),
            HumanMessage(content="\n".join(human_parts)),
        ]

        response = await model.ainvoke(messages)
        content = extract_text_content(getattr(response, "content", ""))

        # Strip markdown fencing if present
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)

        return {
            "ink_script": content,
            "qa_feedback": None,
            "audit_feedback": None,
            "status": "compiling",
            "status_message": "Ink script written; compiling...",
            "outline_review_count": 0,
            "prose_review_count": 0,
            "compile_fix_count": 0,
            "script_rewrite_count": 0,
            "messages": messages,
        }

    return ink_scripter_node


def _make_ink_compile_check_node(if_engine_connector: IfEngineConnector):
    """Non-LLM node: invokes IfEngineConnector.build() on the current script."""

    @log_node("ink_compile_check")
    async def ink_compile_check_node(state: ExperienceGenerationState) -> dict[str, Any]:
        script = state.get("ink_script", "") or ""
        build_result = await if_engine_connector.build(script)

        zero_counters = {
            "outline_review_count": 0,
            "prose_review_count": 0,
            "compile_fix_count": 0,
            "script_rewrite_count": 0,
        }

        if build_result.success:
            log.info("ink_compile_check: compilation succeeded")
            print("ink_compile_check: compilation succeeded")
            return {
                **zero_counters,
                "compiled_output": build_result.output,
                "compiler_errors": [],
                "status": "qa_testing",
                "status_message": "Compilation succeeded; running QA...",
            }

        log.info(
            "ink_compile_check: compilation failed with %d error(s)",
            len(build_result.errors),
        )
        print(f"ink_compile_check: compilation failed: {build_result.errors}")
        return {
            **zero_counters,
            "compiler_errors": build_result.errors,
            "debugger_mode": "ink",
            "debugger_return_node": "ink_compile_check",
            "status": "debugging",
            "status_message": f"Compilation failed with {len(build_result.errors)} error(s); debugging...",
        }

    return ink_compile_check_node


def _make_ink_debugger_node(
    llm_connector: LlmConnector,
    model_name: str | None = None,
):
    """Multi-mode repair node.

    Dispatches on ``state["debugger_mode"]``:

    * ``"ink"`` (default) — fixes Ink compiler errors in ``ink_script``.
    * ``"json"`` — repairs a malformed LLM JSON response stored in
      ``debugger_input`` and writes the fixed text back to ``debugger_input``
      for the caller (``debugger_return_node``) to re-parse.
    """
    _model_cache: list[Any] = []

    @log_node("ink_debugger")
    async def ink_debugger_node(state: ExperienceGenerationState) -> dict[str, Any]:
        if not _model_cache:
            _model_cache.append(llm_connector.get_model(model_name))
        model = _model_cache[0]

        mode = state.get("debugger_mode") or "ink"
        zero_counters: dict[str, Any] = {
            "outline_review_count": 0,
            "prose_review_count": 0,
            "compile_fix_count": 1,  # always increment — guards max-iteration check
            "script_rewrite_count": 0,
        }

        if mode == "json":
            raw_input = state.get("debugger_input") or ""
            messages: list[BaseMessage] = [
                SystemMessage(content=_JSON_DEBUGGER_PROMPT),
                HumanMessage(content=f"Malformed LLM response to fix:\n{raw_input}"),
            ]
            response = await model.ainvoke(messages)
            content = extract_text_content(getattr(response, "content", ""))

            # Strip markdown fencing if present
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content = "\n".join(lines)

            return {
                **zero_counters,
                "debugger_input": content,
                "debugger_mode": None,
                # debugger_return_node is left intact for _route_after_debugger
                "status": "debugging",
                "status_message": "JSON repaired; retrying parse...",
                "messages": messages,
            }

        # --- ink mode (default) ---
        errors_text = "\n".join(state.get("compiler_errors", []))
        messages = [
            SystemMessage(content=_INK_DEBUGGER_PROMPT),
            HumanMessage(
                content=f"Ink script with errors:\n{state.get('ink_script', '')}"
                f"\n\nCompiler errors:\n{errors_text}"
            ),
        ]

        response = await model.ainvoke(messages)
        content = extract_text_content(getattr(response, "content", ""))

        # Strip markdown fencing if present
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)

        return {
            **zero_counters,
            "ink_script": content,
            "debugger_mode": None,
            "status": "recompiling",
            "status_message": "Script debugged; recompiling...",
            "messages": messages,
        }

    return ink_debugger_node


def _make_ink_qa_node(
    llm_connector: LlmConnector,
    model_name: str | None = None,
):
    """Virtual playtest: checks pathing, dead ends, and flow."""
    _model_cache: list[Any] = []

    @log_node("ink_qa")
    async def ink_qa_node(state: ExperienceGenerationState) -> dict[str, Any]:
        if not _model_cache:
            _model_cache.append(llm_connector.get_model(model_name))
        model = _model_cache[0]

        messages = [
            SystemMessage(content=_INK_QA_PROMPT),
            HumanMessage(content=f"Ink script to test:\n{state.get('ink_script', '')}"),
        ]

        response = await model.ainvoke(messages)
        content = extract_text_content(getattr(response, "content", ""))
        result = _parse_json_response(content) or {"status": "PASS", "feedback": ""}

        passed = result.get("status", "").upper() == "PASS"
        log.info("ink_qa: result=%s", "PASS" if passed else "FAIL")

        zero_counters = {
            "outline_review_count": 0,
            "prose_review_count": 0,
            "compile_fix_count": 0,
            "script_rewrite_count": 0,
        }

        if passed:
            return {
                **zero_counters,
                "status": "auditing",
                "status_message": "QA passed; final audit...",
                "last_step_rationale": "ink_qa: Playtest passed — all paths reachable and endings valid.",
                "action_log": [],
            }

        rationale = f"ink_qa: Pathing issue — {_first_sentence(result.get('feedback', ''))}." if result.get('feedback') else "ink_qa: QA found pathing errors in the script."
        return {
            **zero_counters,
            "script_rewrite_count": 1,
            "qa_feedback": result.get("feedback", ""),
            "status": "rewriting_script",
            "status_message": "QA found pathing issues; rewriting script...",
            "last_step_rationale": rationale,
            "action_log": [],
        }

    return ink_qa_node


def _make_ink_auditor_node(
    llm_connector: LlmConnector,
    model_name: str | None = None,
):
    """Final structural audit of the Ink script."""
    _model_cache: list[Any] = []

    @log_node("ink_auditor")
    async def ink_auditor_node(state: ExperienceGenerationState) -> dict[str, Any]:
        if not _model_cache:
            _model_cache.append(llm_connector.get_model(model_name))
        model = _model_cache[0]

        messages = [
            SystemMessage(content=_INK_AUDITOR_PROMPT),
            HumanMessage(content=f"Ink script to audit:\n{state.get('ink_script', '')}"),
        ]

        response = await model.ainvoke(messages)
        content = extract_text_content(getattr(response, "content", ""))
        result = _parse_json_response(content) or {"status": "PASS", "feedback": ""}

        passed = result.get("status", "").upper() == "PASS"
        log.info("ink_auditor: result=%s", "PASS" if passed else "FAIL")

        zero_counters = {
            "outline_review_count": 0,
            "prose_review_count": 0,
            "compile_fix_count": 0,
            "script_rewrite_count": 0,
        }

        if passed:
            return {
                **zero_counters,
                "status": "complete",
                "status_message": "Final audit passed — experience complete!",
                "last_step_rationale": "ink_auditor: Final audit passed — script structure verified.",
                "action_log": [],
            }

        rationale = f"ink_auditor: Structural issue — {_first_sentence(result.get('feedback', ''))}." if result.get('feedback') else "ink_auditor: Auditor flagged structural problems."
        return {
            **zero_counters,
            "script_rewrite_count": 1,
            "audit_feedback": result.get("feedback", ""),
            "status": "rewriting_script",
            "status_message": "Auditor found structural issues; rewriting script...",
            "last_step_rationale": rationale,
            "action_log": [],
        }

    return ink_auditor_node


# ---------------------------------------------------------------------------
# Routing Functions
# ---------------------------------------------------------------------------


def _route_after_outline_author(state: ExperienceGenerationState) -> str:
    """Route after outline_author: research_request → outline_researcher, debugging → ink_debugger, fail → end, else → reviewer."""
    if state.get("research_request"):
        return "outline_researcher"
    status = state.get("status", "")
    if status == "failed":
        return "end"
    if status == "debugging":
        return "ink_debugger"
    return "outline_reviewer"


def _route_after_outline_researcher(state: ExperienceGenerationState) -> str:
    """Route after outline_researcher: always returns to outline_author."""
    return "outline_author"


def _route_after_prose_writer(state: ExperienceGenerationState) -> str:
    """Route after prose_writer: research_request → prose_researcher, else → reviewer."""
    if state.get("research_request"):
        return "prose_researcher"
    return "prose_reviewer"


def _route_after_prose_researcher(state: ExperienceGenerationState) -> str:
    """Route after prose_researcher: always returns to prose_writer."""
    return "prose_writer"


def _route_after_outline_review(state: ExperienceGenerationState) -> str:
    """Route after outline_reviewer: PASS → prose_writer, Story Editor FAIL → arbiter_outline, Tech Only FAIL → loop or fail."""
    status = state.get("status", "")
    if status == "writing_prose":
        return "prose_writer"
    if status == "arbiter_review_outline":
        return "arbiter_outline"
    if status == "failed":
        return "end"
    # Tech-only FAIL — check iteration cap
    total = state.get("outline_review_count", 0)
    if total >= MAX_REVIEW_ITERATIONS:
        log.warning("outline_reviewer: max review iterations reached")
        return "end"
    return "outline_author"


def _route_after_prose_review(state: ExperienceGenerationState) -> str:
    """Route after prose_reviewer: PASS → ink_scripter, Story Editor FAIL → arbiter_prose, Tech Only FAIL → loop or fail."""
    status = state.get("status", "")
    if status == "scripting":
        return "ink_scripter"
    if status == "arbiter_review_prose":
        return "arbiter_prose"
    if status == "failed":
        return "end"
    total = state.get("prose_review_count", 0)
    if total >= MAX_REVIEW_ITERATIONS:
        log.warning("prose_reviewer: max review iterations reached")
        return "end"
    return "prose_writer"


def _route_after_arbiter_outline(state: ExperienceGenerationState) -> str:
    """Route after arbiter_outline: overruled-full-pass → prose_writer, needs-revision → outline_author or fail."""
    status = state.get("status", "")
    if status == "writing_prose":
        return "prose_writer"
    if status == "failed":
        return "end"
    total = state.get("outline_review_count", 0)
    if total >= MAX_REVIEW_ITERATIONS:
        log.warning("arbiter_outline: max review iterations reached")
        return "end"
    return "outline_author"


def _route_after_arbiter_prose(state: ExperienceGenerationState) -> str:
    """Route after arbiter_prose: overruled-full-pass → ink_scripter, needs-revision → prose_writer or fail."""
    status = state.get("status", "")
    if status == "scripting":
        return "ink_scripter"
    if status == "failed":
        return "end"
    total = state.get("prose_review_count", 0)
    if total >= MAX_REVIEW_ITERATIONS:
        log.warning("arbiter_prose: max review iterations reached")
        return "end"
    return "prose_writer"


def _route_after_compile(state: ExperienceGenerationState) -> str:
    """Route after ink_compile_check: success → ink_qa, errors → ink_debugger."""
    status = state.get("status", "")
    if status == "qa_testing":
        return "ink_qa"
    return "ink_debugger"


def _route_after_debugger(state: ExperienceGenerationState) -> str:
    """Route after ink_debugger: use debugger_return_node, or fail on max iterations."""
    total = state.get("compile_fix_count", 0)
    if total >= MAX_COMPILE_FIX_ITERATIONS:
        log.warning("ink_debugger: max fix iterations reached — critical fail")
        return "end"
    return state.get("debugger_return_node") or "ink_compile_check"


def _route_after_qa(state: ExperienceGenerationState) -> str:
    """Route after ink_qa: PASS → ink_auditor, FAIL → ink_scripter."""
    status = state.get("status", "")
    if status == "auditing":
        return "ink_auditor"
    if status == "failed":
        return "end"
    total = sum(
        state.get(k, 0)
        for k in ("script_rewrite_count",)
    )
    if total >= MAX_SCRIPT_REWRITE_ITERATIONS:
        log.warning("ink_qa: max script rewrite iterations reached")
        return "end"
    return "ink_scripter"


def _route_after_auditor(state: ExperienceGenerationState) -> str:
    """Route after ink_auditor: PASS → END, FAIL → ink_scripter."""
    status = state.get("status", "")
    if status == "complete":
        return "end"
    if status == "failed":
        return "end"
    total = sum(
        state.get(k, 0)
        for k in ("script_rewrite_count",)
    )
    if total >= MAX_SCRIPT_REWRITE_ITERATIONS:
        log.warning("ink_auditor: max script rewrite iterations reached")
        return "end"
    return "ink_scripter"


# ---------------------------------------------------------------------------
# Graph Builder
# ---------------------------------------------------------------------------


def build_experience_generation_graph(
    outline_author_connector: LlmConnector,
    outline_reviewer_connector: LlmConnector,
    arbiter_outline_connector: LlmConnector,
    prose_writer_connector: LlmConnector,
    prose_reviewer_connector: LlmConnector,
    arbiter_prose_connector: LlmConnector,
    ink_scripter_connector: LlmConnector,
    ink_debugger_connector: LlmConnector,
    ink_qa_connector: LlmConnector,
    ink_auditor_connector: LlmConnector,
    researcher_connector: LlmConnector,
    embedding_connector: EmbeddingConnector,
    if_engine_connector: IfEngineConnector,
    outline_author_model: str | None = None,
    outline_reviewer_model: str | None = None,
    arbiter_outline_model: str | None = None,
    prose_writer_model: str | None = None,
    prose_reviewer_model: str | None = None,
    arbiter_prose_model: str | None = None,
    ink_scripter_model: str | None = None,
    ink_debugger_model: str | None = None,
    ink_qa_model: str | None = None,
    ink_auditor_model: str | None = None,
    researcher_model: str | None = None,
):
    """Build and compile the experience generation LangGraph StateGraph.

    Parameters
    ----------
    *_connector:
        LLM connectors for each agent node.
    embedding_connector:
        Embedding connector for agentic RAG retriever tools.
    if_engine_connector:
        IF engine connector for compiling Ink scripts.
    *_model:
        Optional model name overrides per node.
    """
    graph = StateGraph(ExperienceGenerationState)

    # --- Nodes ---
    graph.add_node(
        "outline_author",
        _make_outline_author_node(
            outline_author_connector, outline_author_model
        ),
    )
    graph.add_node(
        "outline_researcher",
        _make_researcher_node(
            researcher_connector, embedding_connector, "outline_researcher", researcher_model
        ),
    )
    graph.add_node(
        "outline_reviewer",
        _make_dual_reviewer_node(
            outline_reviewer_connector,
            outline_reviewer_model,
            node_name="outline_reviewer",
            artifact_key="outline",
            feedback_key="outline_feedback",
            counter_key="outline_review_count",
            pass_status="writing_prose",
            fail_status="revising_outline",
            story_rejected_status="arbiter_review_outline",
            pass_message="Outline approved; writing prose...",
            fail_message="Outline needs revision...",
        ),
    )
    graph.add_node(
        "arbiter_outline",
        _make_arbiter_node(
            arbiter_outline_connector,
            arbiter_outline_model,
            node_name="arbiter_outline",
            feedback_key="outline_feedback",
            counter_key="outline_review_count",
            pass_status="writing_prose",
            fail_status="revising_outline",
            pass_message="Outline approved (Story Editor overruled); writing prose...",
            fail_message="Outline needs revision...",
        ),
    )
    graph.add_node(
        "prose_writer",
        _make_prose_writer_node(
            prose_writer_connector, prose_writer_model
        ),
    )
    graph.add_node(
        "prose_researcher",
        _make_researcher_node(
            researcher_connector, embedding_connector, "prose_researcher", researcher_model
        ),
    )
    graph.add_node(
        "prose_reviewer",
        _make_dual_reviewer_node(
            prose_reviewer_connector,
            prose_reviewer_model,
            node_name="prose_reviewer",
            artifact_key="prose_draft",
            feedback_key="prose_feedback",
            counter_key="prose_review_count",
            pass_status="scripting",
            fail_status="revising_prose",
            story_rejected_status="arbiter_review_prose",
            pass_message="Prose approved; scripting...",
            fail_message="Prose needs revision...",
        ),
    )
    graph.add_node(
        "arbiter_prose",
        _make_arbiter_node(
            arbiter_prose_connector,
            arbiter_prose_model,
            node_name="arbiter_prose",
            feedback_key="prose_feedback",
            counter_key="prose_review_count",
            pass_status="scripting",
            fail_status="revising_prose",
            pass_message="Prose approved (Story Editor overruled); scripting...",
            fail_message="Prose needs revision...",
        ),
    )
    graph.add_node(
        "ink_scripter",
        _make_ink_scripter_node(ink_scripter_connector, ink_scripter_model),
    )
    graph.add_node(
        "ink_compile_check",
        _make_ink_compile_check_node(if_engine_connector),
    )
    graph.add_node(
        "ink_debugger",
        _make_ink_debugger_node(ink_debugger_connector, ink_debugger_model),
    )
    graph.add_node(
        "ink_qa",
        _make_ink_qa_node(ink_qa_connector, ink_qa_model),
    )
    graph.add_node(
        "ink_auditor",
        _make_ink_auditor_node(ink_auditor_connector, ink_auditor_model),
    )

    # --- Edges ---
    graph.set_entry_point("outline_author")
    graph.add_conditional_edges(
        "outline_author",
        _route_after_outline_author,
        {
            "outline_researcher": "outline_researcher",
            "outline_reviewer": "outline_reviewer",
            "ink_debugger": "ink_debugger",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "outline_researcher",
        _route_after_outline_researcher,
        {
            "outline_author": "outline_author",
        },
    )
    graph.add_conditional_edges(
        "outline_reviewer",
        _route_after_outline_review,
        {
            "prose_writer": "prose_writer",
            "arbiter_outline": "arbiter_outline",
            "outline_author": "outline_author",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "arbiter_outline",
        _route_after_arbiter_outline,
        {
            "prose_writer": "prose_writer",
            "outline_author": "outline_author",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "prose_writer",
        _route_after_prose_writer,
        {
            "prose_researcher": "prose_researcher",
            "prose_reviewer": "prose_reviewer",
        },
    )
    graph.add_conditional_edges(
        "prose_researcher",
        _route_after_prose_researcher,
        {
            "prose_writer": "prose_writer",
        },
    )
    graph.add_conditional_edges(
        "prose_reviewer",
        _route_after_prose_review,
        {
            "ink_scripter": "ink_scripter",
            "arbiter_prose": "arbiter_prose",
            "prose_writer": "prose_writer",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "arbiter_prose",
        _route_after_arbiter_prose,
        {
            "ink_scripter": "ink_scripter",
            "prose_writer": "prose_writer",
            "end": END,
        },
    )
    graph.add_edge("ink_scripter", "ink_compile_check")
    graph.add_conditional_edges(
        "ink_compile_check",
        _route_after_compile,
        {
            "ink_qa": "ink_qa",
            "ink_debugger": "ink_debugger",
        },
    )
    graph.add_conditional_edges(
        "ink_debugger",
        _route_after_debugger,
        {
            "ink_compile_check": "ink_compile_check",
            "outline_author": "outline_author",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "ink_qa",
        _route_after_qa,
        {
            "ink_auditor": "ink_auditor",
            "ink_scripter": "ink_scripter",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "ink_auditor",
        _route_after_auditor,
        {
            "ink_scripter": "ink_scripter",
            "end": END,
        },
    )

    return graph.compile()
