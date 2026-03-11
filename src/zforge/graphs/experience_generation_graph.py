"""LangGraph experience generation graph.

Eight-node pipeline per docs/Experience Generation.md:

1. outline_author — agentic RAG; produces outline, research notes, title
2. outline_reviewer — dual review (Tech Editor + Story Editor); PASS/FAIL
3. prose_writer — agentic RAG; expands outline into prose draft
4. prose_reviewer — dual review; PASS/FAIL
5. ink_scripter — translates prose draft into Ink script
6. ink_compile_check — non-LLM; invokes IfEngineConnector.build()
7. ink_debugger — fixes compiler errors in Ink script
8. ink_qa — virtual playtest for pathing errors
9. ink_auditor — final structural audit

Tool calls are executed inline within agentic RAG nodes — no ToolNode is
used (per docs/Processes.md § LangGraph tool call pattern).

Implements: src/zforge/graphs/experience_generation_graph.py per
docs/Experience Generation.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph

from zforge.graphs.graph_utils import extract_text_content, log_node, make_retrieve_graph_tool
from zforge.graphs.state import ExperienceGenerationState

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

# ---------------------------------------------------------------------------
# Agent Prompts (from docs/Experience Generation.md § Agent Role & Prompt
# Specifications)
# ---------------------------------------------------------------------------

_OUTLINE_AUTHOR_PROMPT = """\
You are a Lead Narrative Designer. Convert world data and player intent into \
a structural "beat sheet."
1. Query the Z-World hybrid data store to gather specific keys relevant to \
the prompt.
2. Create an Outline: Structured Markdown of scenes and branching points \
(using === knot_names ===).
3. Create Research Notes: A bulleted list of factual data retrieved from \
the Z-World hybrid data store (e.g., location.capital.weather: frozen). \
Keep these distinct from the outline.
4. Adhere to the Player Preference scale (1-10).

When you have gathered enough information and are ready to produce output, \
respond with ONLY a JSON object (no markdown fencing) with exactly these keys:
- "experience_title": a short, evocative title for this experience
- "outline": the full structured Markdown outline
- "research_notes": the bulleted reference data list"""

_TECH_EDITOR_PROMPT = """\
You are the Logic Police. Your focus is the internal consistency of the \
story being built.
1. Plot Holes: Ensure actions have clear motivations and that the player \
can't bypass critical story beats.
2. Branching Value: Ensure choices are meaningful and don't immediately \
"fold" back to the same result.
3. Pacing: Check if the sequence of events feels earned.
4. Output: respond with ONLY a JSON object (no markdown fencing) with \
exactly these keys: "status" (either "PASS" or "FAIL") and "feedback" \
(notes on plot logic)."""

_STORY_EDITOR_PROMPT = """\
You are the Lore Police. Your focus is the external consistency between \
the draft and the Z-World metadata.
1. Lore Adherence: Ensure no violations of world data (e.g., if \
world.tech_level: medieval, flag any mention of steam engines).
2. Fact-Checking: Cross-reference mentions of NPCs, artifacts, or \
locations against the specific key-value pairs provided.
3. Tone: Ensure the draft matches the "voice" established in the world \
metadata.
4. Output: respond with ONLY a JSON object (no markdown fencing) with \
exactly these keys: "status" (either "PASS" or "FAIL") and "feedback" \
(notes on Z-World violations)."""

_PROSE_WRITER_PROMPT = """\
You are a Professional Fiction Author. Expand the Outline into vivid \
narrative text.
1. Use Research Notes (derived from the Z-World data store) for sensory \
details.
2. Write dialogue and descriptions. Mark choices with [Choice Text].
3. Focus on quality of prose while respecting the "World Consistency" notes.

Produce the full prose draft text as your response."""

_INK_SCRIPTER_PROMPT = """\
You are a Narrative Implementation Engineer. Translate the prose draft \
into valid Ink syntax.
1. Use === knots ===, + choices, and -> diverts.
2. Implement state variables as requested in the draft.
3. Ensure all paths lead to a valid -> END.

Produce the complete Ink script as your response — nothing else."""

_INK_DEBUGGER_PROMPT = """\
You are a Senior Game Developer. Fix a broken Ink script based on \
compiler error logs.
1. Fix syntax errors and break infinite loops.
2. Return the functional script without altering the author's prose style.

Produce the complete fixed Ink script as your response — nothing else."""

_INK_QA_PROMPT = """\
You are a Game QA Lead. Perform a "Virtual Playtest" of the final Ink \
script.
1. Pathing: Ensure all knots are reachable.
2. Dead Ends: Flag any path that terminates without a proper -> END.
3. Flow: Identify areas where the player might get "stuck" in a choice \
cycle.

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(title: str) -> str:
    """Convert a title to a kebab-case slug."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def _parse_json_response(content: str) -> dict | None:
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
    embedding_connector: EmbeddingConnector,
    model_name: str | None = None,
):
    """Agentic RAG node: produces outline, research notes, and experience title."""
    from zforge.graphs.document_parsing_graph import _LLAMA_EXECUTOR

    _model_cache: list = []

    @log_node("outline_author")
    async def outline_author_node(state: ExperienceGenerationState) -> dict:
        if not _model_cache:
            _model_cache.append(llm_connector.get_model(model_name))
        model = _model_cache[0]

        z_bundle_root = state["z_bundle_root"]

        # Build retriever tools for this Z-Bundle
        @tool
        async def retrieve_vector(query: str) -> str:
            """Search the Z-Bundle's vector store for semantically similar chunks.

            Args:
                query: Natural language search query.
            """
            import lancedb

            vector_path = f"{z_bundle_root}/vector"
            loop = asyncio.get_running_loop()
            query_vec = await loop.run_in_executor(
                _LLAMA_EXECUTOR,
                lambda: embedding_connector.get_embeddings().embed_query(query),
            )
            db = await lancedb.connect_async(vector_path)
            table = await db.open_table("chunks")
            results_arrow = await (
                await table.search(query_vec, query_type="vector")
            ).limit(5).to_arrow()
            texts = results_arrow.column("text").to_pylist()
            if not texts:
                return "No results found."
            return "\n\n---\n\n".join(t for t in texts if t)

        retrieve_graph = make_retrieve_graph_tool(z_bundle_root)
        tools = [retrieve_vector, retrieve_graph]

        # Build messages
        world_context = json.dumps(state["zworld_kvp"], indent=2)
        prefs_context = json.dumps(state["preferences"], indent=2)
        human_parts = [
            f"World metadata:\n{world_context}",
            f"\nPlayer preferences:\n{prefs_context}",
        ]
        if state.get("player_prompt"):
            human_parts.append(f"\nPlayer request: {state['player_prompt']}")
        if state.get("outline_feedback"):
            human_parts.append(
                f"\nThe reviewers rejected your previous outline with this "
                f"feedback. Revise accordingly:\n{state['outline_feedback']}"
            )

        messages = [
            SystemMessage(content=_OUTLINE_AUTHOR_PROMPT),
            HumanMessage(content="\n".join(human_parts)),
        ]

        # Agentic RAG loop
        bound_model = model.bind_tools(tools)
        tool_map = {t.name: t for t in tools}

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
                        "outline_author: tool %s returned %d chars",
                        tc["name"], len(str(result)),
                    )
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
            log.warning("outline_author: could not parse JSON — preview: %r", content[:300])
            return {
                "status": "failed",
                "failure_reason": "Outline author did not produce valid JSON",
                "status_message": "Experience generation failed: outline output was not valid JSON",
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
    pass_message: str,
    fail_message: str,
):
    """Factory for dual-review nodes (Tech Editor + Story Editor).

    Used by both outline_reviewer and prose_reviewer.
    """
    _model_cache: list = []

    @log_node(node_name)
    async def reviewer_node(state: ExperienceGenerationState) -> dict:
        if not _model_cache:
            _model_cache.append(llm_connector.get_model(model_name))
        model = _model_cache[0]

        artifact = state.get(artifact_key, "") or ""
        world_context = json.dumps(state["zworld_kvp"], indent=2)

        human_content = (
            f"World metadata:\n{world_context}\n\n"
            f"Draft to review:\n{artifact}"
        )

        # Tech Editor review
        tech_messages = [
            SystemMessage(content=_TECH_EDITOR_PROMPT),
            HumanMessage(content=human_content),
        ]
        tech_response = await model.ainvoke(tech_messages)
        tech_content = extract_text_content(getattr(tech_response, "content", ""))
        tech_result = _parse_json_response(tech_content) or {"status": "PASS", "feedback": ""}

        # Story Editor review
        story_messages = [
            SystemMessage(content=_STORY_EDITOR_PROMPT),
            HumanMessage(content=human_content),
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
            return {
                **zero_counters,
                "status": pass_status,
                "status_message": pass_message,
            }

        # Combine feedback from both editors
        feedback_parts = []
        if not tech_pass:
            feedback_parts.append(f"[Technical Editor] {tech_result.get('feedback', '')}")
        if not story_pass:
            feedback_parts.append(f"[Story Editor] {story_result.get('feedback', '')}")
        combined_feedback = "\n\n".join(feedback_parts)

        return {
            **zero_counters,
            counter_key: 1,
            feedback_key: combined_feedback,
            "status": fail_status,
            "status_message": fail_message,
        }

    return reviewer_node


def _make_prose_writer_node(
    llm_connector: LlmConnector,
    embedding_connector: EmbeddingConnector,
    model_name: str | None = None,
):
    """Agentic RAG node: expands outline into vivid prose draft."""
    from zforge.graphs.document_parsing_graph import _LLAMA_EXECUTOR

    _model_cache: list = []

    @log_node("prose_writer")
    async def prose_writer_node(state: ExperienceGenerationState) -> dict:
        if not _model_cache:
            _model_cache.append(llm_connector.get_model(model_name))
        model = _model_cache[0]

        z_bundle_root = state["z_bundle_root"]

        @tool
        async def retrieve_vector(query: str) -> str:
            """Search the Z-Bundle's vector store for semantically similar chunks.

            Args:
                query: Natural language search query.
            """
            import lancedb

            vector_path = f"{z_bundle_root}/vector"
            loop = asyncio.get_running_loop()
            query_vec = await loop.run_in_executor(
                _LLAMA_EXECUTOR,
                lambda: embedding_connector.get_embeddings().embed_query(query),
            )
            db = await lancedb.connect_async(vector_path)
            table = await db.open_table("chunks")
            results_arrow = await (
                await table.search(query_vec, query_type="vector")
            ).limit(5).to_arrow()
            texts = results_arrow.column("text").to_pylist()
            if not texts:
                return "No results found."
            return "\n\n---\n\n".join(t for t in texts if t)

        retrieve_graph = make_retrieve_graph_tool(z_bundle_root)
        tools = [retrieve_vector, retrieve_graph]

        human_parts = [
            f"Outline:\n{state.get('outline', '')}",
            f"\nResearch Notes:\n{state.get('research_notes', '')}",
        ]
        if state.get("prose_feedback"):
            human_parts.append(
                f"\nThe reviewers rejected your previous draft with this "
                f"feedback. Revise accordingly:\n{state['prose_feedback']}"
            )

        messages = [
            SystemMessage(content=_PROSE_WRITER_PROMPT),
            HumanMessage(content="\n".join(human_parts)),
        ]

        bound_model = model.bind_tools(tools)
        tool_map = {t.name: t for t in tools}

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
                        "prose_writer: tool %s returned %d chars",
                        tc["name"], len(str(result)),
                    )
                    messages.append(
                        ToolMessage(
                            content=str(result),
                            tool_call_id=tc["id"],
                            name=tc["name"],
                        )
                    )

        content = extract_text_content(getattr(response, "content", ""))

        return {
            "prose_draft": content,
            "prose_feedback": None,
            "status": "reviewing_prose",
            "status_message": "Prose draft written; under review...",
            "outline_review_count": 0,
            "prose_review_count": 0,
            "compile_fix_count": 0,
            "script_rewrite_count": 0,
            "messages": messages,
        }

    return prose_writer_node


def _make_ink_scripter_node(
    llm_connector: LlmConnector,
    model_name: str | None = None,
):
    """Translates prose draft into Ink script."""
    _model_cache: list = []

    @log_node("ink_scripter")
    async def ink_scripter_node(state: ExperienceGenerationState) -> dict:
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
    async def ink_compile_check_node(state: ExperienceGenerationState) -> dict:
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
            "status": "debugging",
            "status_message": f"Compilation failed with {len(build_result.errors)} error(s); debugging...",
        }

    return ink_compile_check_node


def _make_ink_debugger_node(
    llm_connector: LlmConnector,
    model_name: str | None = None,
):
    """Fixes compiler errors in Ink script."""
    _model_cache: list = []

    @log_node("ink_debugger")
    async def ink_debugger_node(state: ExperienceGenerationState) -> dict:
        if not _model_cache:
            _model_cache.append(llm_connector.get_model(model_name))
        model = _model_cache[0]

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
            "ink_script": content,
            "status": "recompiling",
            "status_message": "Script debugged; recompiling...",
            "outline_review_count": 0,
            "prose_review_count": 0,
            "compile_fix_count": 1,
            "script_rewrite_count": 0,
            "messages": messages,
        }

    return ink_debugger_node


def _make_ink_qa_node(
    llm_connector: LlmConnector,
    model_name: str | None = None,
):
    """Virtual playtest: checks pathing, dead ends, and flow."""
    _model_cache: list = []

    @log_node("ink_qa")
    async def ink_qa_node(state: ExperienceGenerationState) -> dict:
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
            }

        return {
            **zero_counters,
            "script_rewrite_count": 1,
            "qa_feedback": result.get("feedback", ""),
            "status": "rewriting_script",
            "status_message": "QA found pathing issues; rewriting script...",
        }

    return ink_qa_node


def _make_ink_auditor_node(
    llm_connector: LlmConnector,
    model_name: str | None = None,
):
    """Final structural audit of the Ink script."""
    _model_cache: list = []

    @log_node("ink_auditor")
    async def ink_auditor_node(state: ExperienceGenerationState) -> dict:
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
            }

        return {
            **zero_counters,
            "script_rewrite_count": 1,
            "audit_feedback": result.get("feedback", ""),
            "status": "rewriting_script",
            "status_message": "Auditor found structural issues; rewriting script...",
        }

    return ink_auditor_node


# ---------------------------------------------------------------------------
# Routing Functions
# ---------------------------------------------------------------------------


def _route_after_outline_review(state: ExperienceGenerationState) -> str:
    """Route after outline_reviewer: PASS → prose_writer, FAIL → loop or fail."""
    status = state.get("status", "")
    if status == "writing_prose":
        return "prose_writer"
    if status == "failed":
        return "end"
    # FAIL — check iteration cap
    total = sum(
        state.get(k, 0)
        for k in ("outline_review_count",)
    )
    if total >= MAX_REVIEW_ITERATIONS:
        log.warning("outline_reviewer: max review iterations reached")
        return "end"
    return "outline_author"


def _route_after_prose_review(state: ExperienceGenerationState) -> str:
    """Route after prose_reviewer: PASS → ink_scripter, FAIL → loop or fail."""
    status = state.get("status", "")
    if status == "scripting":
        return "ink_scripter"
    if status == "failed":
        return "end"
    total = sum(
        state.get(k, 0)
        for k in ("prose_review_count",)
    )
    if total >= MAX_REVIEW_ITERATIONS:
        log.warning("prose_reviewer: max review iterations reached")
        return "end"
    return "prose_writer"


def _route_after_compile(state: ExperienceGenerationState) -> str:
    """Route after ink_compile_check: success → ink_qa, errors → ink_debugger."""
    status = state.get("status", "")
    if status == "qa_testing":
        return "ink_qa"
    return "ink_debugger"


def _route_after_debugger(state: ExperienceGenerationState) -> str:
    """Route after ink_debugger: retry compile or fail on max iterations."""
    total = sum(
        state.get(k, 0)
        for k in ("compile_fix_count",)
    )
    if total >= MAX_COMPILE_FIX_ITERATIONS:
        log.warning("ink_debugger: max compile fix iterations reached — critical fail")
        return "end"
    return "ink_compile_check"


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
    prose_writer_connector: LlmConnector,
    prose_reviewer_connector: LlmConnector,
    ink_scripter_connector: LlmConnector,
    ink_debugger_connector: LlmConnector,
    ink_qa_connector: LlmConnector,
    ink_auditor_connector: LlmConnector,
    embedding_connector: EmbeddingConnector,
    if_engine_connector: IfEngineConnector,
    outline_author_model: str | None = None,
    outline_reviewer_model: str | None = None,
    prose_writer_model: str | None = None,
    prose_reviewer_model: str | None = None,
    ink_scripter_model: str | None = None,
    ink_debugger_model: str | None = None,
    ink_qa_model: str | None = None,
    ink_auditor_model: str | None = None,
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
            outline_author_connector, embedding_connector, outline_author_model
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
            pass_message="Outline approved; writing prose...",
            fail_message="Outline needs revision...",
        ),
    )
    graph.add_node(
        "prose_writer",
        _make_prose_writer_node(
            prose_writer_connector, embedding_connector, prose_writer_model
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
            pass_message="Prose approved; scripting...",
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
    graph.add_edge("outline_author", "outline_reviewer")
    graph.add_conditional_edges(
        "outline_reviewer",
        _route_after_outline_review,
        {
            "prose_writer": "prose_writer",
            "outline_author": "outline_author",
            "end": END,
        },
    )
    graph.add_edge("prose_writer", "prose_reviewer")
    graph.add_conditional_edges(
        "prose_reviewer",
        _route_after_prose_review,
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
