# IF Engine Abstraction Layer

Z-Forge supports multiple interactive fiction engines through a common abstraction layer. This allows the experience generation system to target different IF platforms (e.g., ink, Inform 7, TADS) without coupling the generation logic to any specific engine.

## IfEngineConnector Interface

The `IfEngineConnector` is a Python abstract base class (ABC) that each supported IF engine must implement.

### Interface Methods

#### Get Engine Name
Returns the canonical name of the IF engine.

- **Signature**: `def get_engine_name(self) -> str`
- **Returns**: A fixed string identifying the engine (e.g., `"ink"`, `"Inform 7"`, `"TADS"`)
- **Usage**: Used for logging, UI display, and configuration selection.

#### Get File Extension
Returns the file extension for compiled output files from this engine.

- **Signature**: `def get_file_extension(self) -> str`
- **Returns**: A fixed string with the file extension including the leading dot (e.g., `".ink.json"`, `".gblorb"`, `".t3"`)
- **Usage**: Used when saving compiled experiences to storage.

#### Get Script Prompt
Returns engine-specific guidance for LLM agents writing scripts in this engine's language.

- **Signature**: `def get_script_prompt(self) -> str`
- **Returns**: A text block describing syntax requirements, common pitfalls, and best practices specific to this engine's scripting language.
- **Usage**: Injected as a system prompt for the Scripter agent during experience generation. This ensures the LLM produces syntactically correct scripts for the target engine.

**Example for ink**:
```
ink scripts use a specific syntax for interactive narrative. Key requirements:
- Knots are declared with === knot_name ===
- Stitches within knots use = stitch_name
- Choices use * for one-time and + for sticky choices
- Diverts use -> knot_name
- Variables are declared with VAR and modified with ~
- Use <> for glue to join text across lines
- End threads with -> DONE and end the story with -> END
```

**Example for Inform 7**:
```
Inform 7 uses natural language syntax with specific formatting requirements:
- Inform specifically requires tabs and not spaces for indentation. Do not use spaces to indent.
- Rooms and objects must be declared before they can be referenced.
- Use quotation marks for say phrases.
- Rules follow the pattern: "Instead of [action]: [result]"
```

#### Build
Compiles a script in the engine's language into a runnable format.

- **Signature**: `async def build(self, script: str) -> BuildResult`
- **Parameters**:
  - `script`: The complete source code in the engine's scripting language.
- **Returns**: A `BuildResult` dataclass containing:
  - `output: bytes | None`: The compiled binary/JSON output, or `None` if compilation failed.
  - `warnings: list[str]`: Compiler warnings that don't prevent execution.
  - `errors: list[str]`: Compiler errors that prevent successful compilation.
- **Usage**: Called after the Scripter produces a script. Errors are fed back to the Scripter for correction; warnings may be logged or surfaced to editors.

#### Start Experience
Initializes a new playthrough of a compiled experience.

- **Signature**: `async def start_experience(self, compiled_data: bytes) -> str`
- **Parameters**:
  - `compiled_data`: The compiled experience data (output from `build()`).
- **Returns**: The initial text output from the experience (e.g., title screen, opening narrative, initial room description).
- **Usage**: Called when a player begins a new experience. The connector maintains internal state for the active playthrough.

#### Take Action
Processes player input and advances the experience state.

- **Signature**: `async def take_action(self, input: str) -> ActionResult`
- **Parameters**:
  - `input`: The player's text input (e.g., a typed command or selected choice).
- **Returns**: An `ActionResult` dataclass containing:
  - `text: str`: The narrative response to display to the player.
  - `choices: list[str] | None`: For choice-based engines, the available choices (`None` for parser-based engines).
  - `is_complete: bool`: Whether the experience has reached an ending.
- **Usage**: Called each time the player provides input during gameplay.

#### Save State
Serializes the current playthrough state to bytes for persistence.

- **Signature**: `async def save_state(self) -> bytes`
- **Returns**: Bytes representing the complete current state of the playthrough.
- **Usage**: Called by the ExperienceManager when the player saves their progress.

#### Restore State
Restores a playthrough from a previously saved state.

- **Signature**: `async def restore_state(self, saved_state: bytes) -> ActionResult`
- **Parameters**:
  - `saved_state`: The bytes previously returned by `save_state()`.
- **Returns**: An `ActionResult` containing the current narrative text at the restored position and the available choices (matching the format returned by `take_action()`). This allows the UI to render both text and choices without a separate call.
- **Usage**: Called by the ExperienceManager when the player loads a saved game.

**TODO**: Future enhancements needed:
- Inventory management and state queries
- Undo support
- Metadata retrieval (current location, score, turns, etc.)
- Experience completion detection and ending classification

## Supported Engines

### ink (Primary)
- **Engine Name**: `"ink"`
- **File Extension**: `".ink.json"`
- **Compiler**: inkjs (via Python JS bridge — see below)
- **Runtime**: inkjs (via Python JS bridge)
- **Script Language**: ink markup language
- **Interaction Model**: Choice-based
- **Implementation**: See [Ink Engine Connector](Ink%20Engine%20Connector.md)

### Future Engines (Planned)
- **Inform 7**: Natural language IF authoring, parser-based interaction, compiles to Glulx (.gblorb)
- **TADS 3**: Object-oriented IF development, parser-based interaction
- **Twine/Twee**: Hypertext-based interactive fiction

## Integration with Experience Generation

The IF Engine Abstraction Layer integrates with the experience generation pipeline at several points:

1. **Script Prompt Injection**: The connector's `get_script_prompt()` output is provided to the Scripter agent as a system prompt, ensuring engine-specific syntax compliance.

2. **Compilation Validation**: The `build()` method is called to validate scripts during the generation loop. Errors trigger revision cycles with the Scripter.

3. **Engine Identification**: The `get_engine_name()` return value is included in system prompts so agents understand which engine they're targeting.

4. **Experience Playback**: Once generation is complete, `start_experience()` and `take_action()` power the player's interaction with the finished experience.

## Configuration

The active IF engine is configured at the application level.

```python
# Conceptual configuration
class ZForgeConfig:
    default_if_engine: str = "ink"  # e.g., "ink", "inform7"
```

## Data Types

### BuildResult
```python
from dataclasses import dataclass, field

@dataclass
class BuildResult:
    output: bytes | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.output is not None and not self.errors
```

### ActionResult
```python
@dataclass
class ActionResult:
    text: str
    choices: list[str] | None = None
    is_complete: bool = False
```
