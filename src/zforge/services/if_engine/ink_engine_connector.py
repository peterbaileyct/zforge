"""Ink Engine Connector implementation.

Uses py-mini-racer + inkjs for in-process ink compilation and runtime.
Implements: src/zforge/services/if_engine/ink_engine_connector.py per
docs/Ink Engine Connector.md and docs/IF Engine Abstraction Layer.md.

Note: restore_state() returns ActionResult per the ABC spec in
docs/IF Engine Abstraction Layer.md (not str as shown in the
Ink Engine Connector doc example).
"""

from __future__ import annotations

import json
from pathlib import Path

import quickjs

from zforge.models.results import ActionResult, BuildResult
from zforge.services.if_engine.if_engine_connector import IfEngineConnector


_ASSETS_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "assets"


class InkEngineConnector(IfEngineConnector):
    """IF engine connector for ink via quickjs + inkjs."""

    def __init__(self) -> None:
        self._ctx: quickjs.Context | None = None

    async def initialize(self) -> None:
        """Must be called before any other method."""
        if self._ctx is not None:
            return
        ink_js = (_ASSETS_DIR / "ink-full.js").read_text(encoding="utf-8")
        ctx = quickjs.Context()
        ctx.eval(ink_js)
        self._ctx = ctx

    def _ensure_initialized(self) -> None:
        if self._ctx is None:
            raise RuntimeError(
                "InkEngineConnector.initialize() must be called first"
            )

    def get_engine_name(self) -> str:
        return "ink"

    def get_file_extension(self) -> str:
        return ".ink.json"

    def get_script_prompt(self) -> str:
        return """
ink scripts use a specific syntax for interactive narrative. Key requirements:
- IMPORTANT: The script MUST start with a divert to the opening knot (e.g., -> opening) at the very top of the file, BEFORE any knot declarations. Without this, the story will not run.
- Knots are declared with === knot_name ===
- Stitches within knots use = stitch_name
- Choices use * for one-time and + for sticky choices
- Choice text in brackets [] is not shown after selection
- Diverts use -> knot_name or -> knot_name.stitch_name
- Variables are declared with VAR name = value and modified with ~ name = value
- CRITICAL: ~ assignments MUST be on their own dedicated line — NEVER on the same line as narrative text or dialogue. WRONG: `"She smiled." ~ courage = true` (the assignment becomes visible text!). RIGHT: put `~ courage = true` on its own separate line before or after the narrative.
- Use { condition: text } for conditional text
- Use { variable } to print variable values inline
- Use <> for glue to join text across lines without whitespace
- End threads with -> DONE and end the story with -> END
- Comments use // for single line and /* */ for multi-line
- External functions and INCLUDE are not supported in Z-Forge

CRITICAL - Narrative vs. Choices:
- ONLY player actions/decisions should be choices (lines starting with * or +)
- Narrative text, NPC dialogue, and scene descriptions must be plain text (NO * or + prefix)
- WRONG: * "Hello!" said the dragon. (This makes NPC dialogue a clickable choice!)
- RIGHT: "Hello!" said the dragon.
         * [Greet the dragon] "Hello to you too!"
- WRONG: * Choose your path:  (This makes instructions a choice!)
- RIGHT: Choose your path:
         * [Go left] -> left_path
         * [Go right] -> right_path

Script structure example:
VAR trust = 0

-> opening

=== opening ===
The forest stretched endlessly before you. A wise owl perched nearby.
"Welcome, traveler," the owl hooted softly.
* [Ask for directions]
    "Which way to the village?" you ask.
    -> village_directions
* [Ignore the owl]
    You walk past without a word.
    -> forest_path

=== village_directions ===
The owl ruffles its feathers thoughtfully.
"Follow the stream north," it advises.
* [Thank the owl] -> thank_owl
* [Ask another question] -> more_questions

Common patterns:
- Branching: Use choices leading to different knots
- Loops: Use sticky choices (+) for repeatable options
- State tracking: Use VAR for counters, flags, and relationships
- Conditional choices: Use { condition } before * or + to show choices conditionally
"""

    async def build(self, script: str) -> BuildResult:
        self._ensure_initialized()
        escaped = json.dumps(script)
        result = self._ctx.eval(f"""
            (function() {{
                try {{
                    var compiler = new inkjs.Compiler({escaped});
                    var story = compiler.Compile();
                    return JSON.stringify({{
                        success: true,
                        json: story.ToJson(),
                        warnings: compiler.warnings || []
                    }});
                }} catch (e) {{
                    return JSON.stringify({{
                        success: false,
                        errors: [e.toString()],
                        warnings: []
                    }});
                }}
            }})()
        """)
        data = json.loads(result)
        if data["success"]:
            return BuildResult(
                output=data["json"].encode("utf-8"),
                warnings=data.get("warnings", []),
                errors=[],
            )
        return BuildResult(
            output=None,
            warnings=data.get("warnings", []),
            errors=data.get("errors", []),
        )

    async def start_experience(self, compiled_data: bytes) -> str:
        self._ensure_initialized()
        json_str = compiled_data.decode("utf-8")
        # inkjs.Story expects a parsed JSON object. Ensure we pass a JS object
        # by calling JSON.parse(...) on the compiled JSON string.
        self._ctx.eval(
            f"globalThis._inkStory = new inkjs.Story(JSON.parse({json.dumps(json_str)}));"
        )
        # Diagnostic: inspect initial story state and currentChoices to aid debugging.
        try:
            diag = self._ctx.eval(
                "JSON.stringify({canContinue: globalThis._inkStory.canContinue, choices: globalThis._inkStory.currentChoices.map(function(c){return c.text;})})"
            )
            print("InkEngineConnector.start_experience: story diag ->", diag)
        except Exception as e:
            print("InkEngineConnector.start_experience: diag eval failed:", e)
        text = self._continue_story()
        print("InkEngineConnector.start_experience: continued text type=", type(text), "repr=", repr(text))
        return text

    def _continue_story(self) -> str:
        result = self._ctx.eval("""
            (function() {
                var story = globalThis._inkStory;
                var text = "";
                while (story.canContinue) { text += story.Continue(); }
                return text;
            })()
        """)
        print("InkEngineConnector._continue_story: raw result repr=", JSON.stringify({val: result}) )
        # Return the raw string — caller may inspect/strip as needed.
        try:
            return result
        except Exception:
            return str(result)

    async def take_action(self, input: str) -> ActionResult:
        self._ensure_initialized()
        choice_index = int(input)
        self._ctx.eval(
            f"globalThis._inkStory.ChooseChoiceIndex({choice_index});"
        )
        text = self._continue_story()
        state = json.loads(self._ctx.eval("""
            JSON.stringify({
                choices: globalThis._inkStory.currentChoices.map(function(c){return c.text;}),
                isComplete: !globalThis._inkStory.canContinue && globalThis._inkStory.currentChoices.length === 0
            })
        """))
        choices = state["choices"] or None
        return ActionResult(
            text=text, choices=choices, is_complete=state["isComplete"]
        )

    async def save_state(self) -> bytes:
        self._ensure_initialized()
        result = self._ctx.eval(
            "JSON.stringify(globalThis._inkStory.state.ToJson())"
        )
        return result.encode("utf-8")

    async def restore_state(self, saved_state: bytes) -> ActionResult:
        """Restore state and return ActionResult (per ABC spec)."""
        self._ensure_initialized()
        state_json = saved_state.decode("utf-8")
        self._ctx.eval(
            f"globalThis._inkStory.state.LoadJson({json.dumps(state_json)});"
        )
        text = self._continue_story()
        state = json.loads(self._ctx.eval("""
            JSON.stringify({
                choices: globalThis._inkStory.currentChoices.map(function(c){return c.text;}),
                isComplete: !globalThis._inkStory.canContinue && globalThis._inkStory.currentChoices.length === 0
            })
        """))
        choices = state["choices"] or None
        return ActionResult(
            text=text, choices=choices, is_complete=state["isComplete"]
        )

    # --- Helper methods (not part of abstract interface) ---

    async def get_current_choices(self) -> list[str]:
        """Get current available choices without making a selection."""
        self._ensure_initialized()
        return json.loads(self._ctx.eval(
            "JSON.stringify(globalThis._inkStory.currentChoices.map(function(c){return c.text;}))"
        ))

    async def get_variable(self, name: str):
        """Get current value of a story variable."""
        self._ensure_initialized()
        return json.loads(self._ctx.eval(
            f"JSON.stringify(globalThis._inkStory.variablesState[{json.dumps(name)}])"
        ))

    async def set_variable(self, name: str, value) -> None:
        """Set a story variable."""
        self._ensure_initialized()
        self._ctx.eval(
            f"globalThis._inkStory.variablesState[{json.dumps(name)}] = {json.dumps(value)};"
        )

    def dispose(self) -> None:
        """Release the JS runtime."""
        self._ctx = None
