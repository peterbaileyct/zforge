# Ink Engine Connector

Implementation specification for the `InkEngineConnector`, which implements the [IF Engine Abstraction Layer](IF%20Engine%20Abstraction%20Layer.md) interface for the [ink](https://www.inklestudios.com/ink/) interactive fiction scripting language.

## Overview

The ink engine connector uses [inkjs](https://github.com/y-lohse/inkjs) (v2.4.0) running inside [py-mini-racer](https://github.com/bpcreech/PyMiniRacer) (Python-embedded V8) to provide both compilation and runtime execution. This approach allows Z-Forge to compile and run ink stories entirely in-process without a separate server or native binaries.

## Dependencies

### Python Package
Add to `pyproject.toml`:
```toml
[project.dependencies]
py-mini-racer = ">=0.12"
```

### JavaScript Asset
The inkjs library is bundled as a project asset:
- **File**: `assets/ink-full.js` (~249KB)
- **Version**: 2.4.0
- **Contents**: Complete inkjs distribution including compiler and runtime
- **Source**: https://unpkg.com/inkjs@2.4.0/dist/ink-full.js

## Implementation Location

```
src/zforge/services/if_engine/
├── if_engine_connector.py      # Abstract base class
└── ink_engine_connector.py     # ink implementation
```

## InkEngineConnector Class

### Initialization

```python
import json
from py_mini_racer import MiniRacer
from importlib.resources import files
from zforge.services.if_engine.if_engine_connector import IfEngineConnector, BuildResult, ActionResult

class InkEngineConnector(IfEngineConnector):
    def __init__(self):
        self._ctx: MiniRacer | None = None

    async def initialize(self) -> None:
        """Must be called before any other method."""
        if self._ctx is not None:
            return
        ink_js = files("zforge").joinpath("../../../assets/ink-full.js").read_text()
        self._ctx = MiniRacer()
        self._ctx.eval(ink_js)

    def _ensure_initialized(self) -> None:
        if self._ctx is None:
            raise RuntimeError("InkEngineConnector.initialize() must be called first")
```

### Interface Implementation

#### get_engine_name()
```python
    def get_engine_name(self) -> str:
        return "ink"
```

#### get_file_extension()
```python
    def get_file_extension(self) -> str:
        return ".ink.json"
```

#### get_script_prompt()
```python
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
''';
```

#### build()

Compilation uses the inkjs `Compiler` class:

```python
    async def build(self, script: str) -> BuildResult:
        self._ensure_initialized()
        escaped = json.dumps(script)  # produces a JS-safe quoted string
        result = self._ctx.eval(f'''
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
        ''')
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
```

#### start_experience()

Starts a new playthrough by loading compiled JSON into an ink Story:

```python
    async def start_experience(self, compiled_data: bytes) -> str:
        self._ensure_initialized()
        json_str = compiled_data.decode("utf-8")
        self._ctx.eval(f'window._inkStory = new inkjs.Story({json.dumps(json_str)});')
        return self._continue_story()

    def _continue_story(self) -> str:
        result = self._ctx.eval('''
            (function() {
                var story = window._inkStory;
                var text = "";
                while (story.canContinue) { text += story.Continue(); }
                return text;
            })()
        ''')
        return result.strip()
```

#### take_action()

Processes player choice and returns the result:

```python
    async def take_action(self, input: str) -> ActionResult:
        self._ensure_initialized()
        choice_index = int(input)  # ink uses numeric choice indices
        self._ctx.eval(f'window._inkStory.ChooseChoiceIndex({choice_index});')
        text = self._continue_story()
        state = json.loads(self._ctx.eval('''
            JSON.stringify({
                choices: window._inkStory.currentChoices.map(c => c.text),
                isComplete: !window._inkStory.canContinue && window._inkStory.currentChoices.length === 0
            })
        '''))
        choices = state["choices"] or None
        return ActionResult(text=text, choices=choices, is_complete=state["isComplete"])
```

#### save_state()

```python
    async def save_state(self) -> bytes:
        self._ensure_initialized()
        result = self._ctx.eval('JSON.stringify(window._inkStory.state.ToJson())')
        return result.encode("utf-8")
```

#### restore_state()

```python
    async def restore_state(self, saved_state: bytes) -> str:
        self._ensure_initialized()
        state_json = saved_state.decode("utf-8")
        self._ctx.eval(f'window._inkStory.state.LoadJson({json.dumps(state_json)});')
        return self._continue_story()
```

## inkjs API Reference

Key inkjs classes and methods used by this connector:

### Compiler
```javascript
// Create compiler with ink source
var compiler = new inkjs.Compiler(inkSourceString);

// Compile to Story object (throws on fatal errors)
var story = compiler.Compile();

// Access compiler diagnostics
compiler.errors   // Array of error strings
compiler.warnings // Array of warning strings
```

### Story
```javascript
// Create from compiled JSON
var story = new inkjs.Story(jsonString);

// Continue narrative
story.canContinue        // Boolean: is there more text?
story.Continue()         // Get next paragraph, advances state
story.ContinueMaximally() // Get all available text at once

// Choices
story.currentChoices     // Array of Choice objects
story.ChooseChoiceIndex(n) // Select choice by index (0-based)

// Choice object properties
choice.text              // Display text for the choice
choice.index             // Index to pass to ChooseChoiceIndex

// State serialization
story.state.ToJson()     // Serialize state to JSON string
story.state.LoadJson(s)  // Restore state from JSON string

// Compiled story serialization
story.ToJson()           // Get compiled JSON representation
```

### Variables
```javascript
// Read variables
var value = story.variablesState["variableName"];

// Write variables
story.variablesState["variableName"] = newValue;
```

## Choice Handling

The ink runtime is choice-based. The UI layer must:

1. After `start_experience()` or `take_action()`, query available choices
2. Display choices to the player as numbered options or buttons
3. Pass the selected choice index (0-based as a string) to `take_action()`

Example flow:
```python
# Start experience
opening_text = await connector.start_experience(compiled_data)
openingchoices = await connector.get_current_choices()

# Player selects choice 1
result = await connector.take_action('1')
# result.text — narrative response
# result.choices — next choices (or None if story ended)
# result.is_complete — True if story has ended
```

## Helper Methods

Additional convenience methods (not part of the abstract interface):

```python
    async def get_current_choices(self) -> list[str]:
        """Get current available choices without making a selection."""
        self._ensure_initialized()
        return json.loads(self._ctx.eval(
            'JSON.stringify(window._inkStory.currentChoices.map(c => c.text))'
        ))

    async def get_variable(self, name: str):
        """Get current value of a story variable."""
        self._ensure_initialized()
        return json.loads(self._ctx.eval(
            f'JSON.stringify(window._inkStory.variablesState[{json.dumps(name)}])'
        ))

    async def set_variable(self, name: str, value) -> None:
        """Set a story variable."""
        self._ensure_initialized()
        self._ctx.eval(
            f'window._inkStory.variablesState[{json.dumps(name)}] = {json.dumps(value)};'
        )

    def dispose(self) -> None:
        """Release the JS runtime."""
        self._ctx = None
```

## Error Handling

### Compilation Errors
ink compilation errors are returned in `BuildResult.errors`. Common errors include:
- Syntax errors (malformed knots, invalid divert targets)
- Undefined knot/stitch references
- Invalid variable operations

### Runtime Errors
The ink runtime may throw errors during playthrough:
- Selecting an invalid choice index
- Diverting to a non-existent knot
- Stack overflow from infinite loops

Wrap `take_action()` calls in try-except and present errors appropriately to users.

## Platform Considerations

### py-mini-racer Availability
`py-mini-racer` ships a pre-built V8 binary via pip and supports:
- ✅ macOS (arm64 and x86_64)
- ✅ Windows
- ✅ Linux
- ⚠️ iOS/Android: BeeWare's mobile support may require a different approach (Node.js subprocess via `asyncio.create_subprocess_exec`) — TBD.
- ⚠️ Web: Not applicable; a separate web build strategy is needed (e.g., WebAssembly inkjs via Pyodide or a server-side compilation endpoint).

### Performance
- `initialize()`: ~150–300ms (V8 startup + JS load)
- Compilation: <1s for typical scripts
- Runtime operations: <10ms per call

### Memory
- Each `InkEngineConnector` instance maintains its own V8 context
- Call `dispose()` when done to release V8 resources

## Testing

Example test script for validation:

```ink
VAR health = 100

=== start ===
You stand at a crossroads.
* [Go left] -> left_path
* [Go right] -> right_path

=== left_path ===
You find a healing potion.
~ health = health + 20
Your health is now {health}.
-> ending

=== right_path ===
A monster attacks!
~ health = health - 30
Your health is now {health}.
-> ending

=== ending ===
{ health > 50:
    You survived the adventure!
- else:
    You barely made it out alive.
}
-> END
```

## Related Documentation
- [IF Engine Abstraction Layer](IF%20Engine%20Abstraction%20Layer.md) - Interface specification
- [Experience Generation](Experience%20Generation.md) - How scripts are generated
- [User Experience](User%20Experience.md) - Gameplay UI integration
