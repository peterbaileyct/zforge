# IF Engine Abstraction Layer

Z-Forge supports multiple interactive fiction engines through a common abstraction layer. This allows the experience generation system to target different IF platforms (e.g., ink, Inform 7, TADS) without coupling the generation logic to any specific engine.

## IfEngineConnector Interface

The `IfEngineConnector` is an abstract interface that each supported IF engine must implement. This enables the experience generation pipeline to remain engine-agnostic while leveraging engine-specific compilation and runtime features.

### Interface Methods

#### Get Engine Name
Returns the canonical name of the IF engine.

- **Signature**: `String getEngineName()`
- **Returns**: A fixed string identifying the engine (e.g., `"ink"`, `"Inform 7"`, `"TADS"`)
- **Usage**: Used for logging, UI display, and configuration selection.

#### Get File Extension
Returns the file extension for compiled output files from this engine.

- **Signature**: `String getFileExtension()`
- **Returns**: A fixed string with the file extension including the leading dot (e.g., `".ink.json"`, `".gblorb"`, `".t3"`)
- **Usage**: Used when saving compiled experiences to storage.

#### Get Script Prompt
Returns engine-specific guidance for LLM agents writing scripts in this engine's language.

- **Signature**: `String getScriptPrompt()`
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

- **Signature**: `Future<BuildResult> build(String script)`
- **Parameters**:
  - `script`: The complete source code in the engine's scripting language.
- **Returns**: A `BuildResult` object containing:
  - `Uint8List? output`: The compiled binary/JSON output, or `null` if compilation failed.
  - `List<String> warnings`: Compiler warnings that don't prevent execution.
  - `List<String> errors`: Compiler errors that prevent successful compilation.
- **Usage**: Called after the Scripter produces a script. Errors are fed back to the Scripter for correction; warnings may be logged or surfaced to editors.

#### Start Experience
Initializes a new playthrough of a compiled experience.

- **Signature**: `Future<String> startExperience(Uint8List compiledData)`
- **Parameters**:
  - `compiledData`: The compiled experience data (output from `build()`).
- **Returns**: The initial text output from the experience (e.g., title screen, opening narrative, initial room description).
- **Usage**: Called when a player begins a new experience. The connector maintains internal state for the active playthrough.

#### Take Action
Processes player input and advances the experience state.

- **Signature**: `Future<ActionResult> takeAction(String input)`
- **Parameters**:
  - `input`: The player's text input (e.g., a typed command or selected choice).
- **Returns**: An `ActionResult` object containing:
  - `String text`: The narrative response to display to the player.
  - `List<String>? choices`: For choice-based engines, the available choices (null for parser-based engines).
  - `bool isComplete`: Whether the experience has reached an ending.
- **Usage**: Called each time the player provides input during gameplay.

#### Save State
Serializes the current playthrough state to a byte array for persistence.

- **Signature**: `Future<Uint8List> saveState()`
- **Returns**: A byte array representing the complete current state of the playthrough.
- **Usage**: Called by the ExperienceManager when the player saves their progress. The returned bytes are written to local storage.

#### Restore State
Restores a playthrough from a previously saved state.

- **Signature**: `Future<String> restoreState(Uint8List savedState)`
- **Parameters**:
  - `savedState`: The byte array previously returned by `saveState()`.
- **Returns**: The current text output after restoration (typically the last displayed text before save).
- **Usage**: Called by the ExperienceManager when the player loads a saved game. The connector's internal state is fully replaced by the saved state.

**TODO**: Future enhancements needed:
- Inventory management and state queries
- Undo support
- Metadata retrieval (current location, score, turns, etc.)
- Experience completion detection and ending classification

## Supported Engines

### ink (Primary)
- **Engine Name**: `"ink"`
- **File Extension**: `".ink.json"`
- **Compiler**: inkjs (via flutter_js)
- **Runtime**: inkjs (via flutter_js)
- **Script Language**: ink markup language
- **Interaction Model**: Choice-based
- **Implementation**: See [Ink Engine Connector](Ink%20Engine%20Connector.md)

### Future Engines (Planned)
- **Inform 7**: Natural language IF authoring, parser-based interaction, compiles to Glulx (.gblorb)
- **TADS 3**: Object-oriented IF development, parser-based interaction
- **Twine/Twee**: Hypertext-based interactive fiction

## Integration with Experience Generation

The IF Engine Abstraction Layer integrates with the experience generation pipeline at several points:

1. **Script Prompt Injection**: The connector's `getScriptPrompt()` output is provided to the Scripter agent as a system prompt, ensuring engine-specific syntax compliance.

2. **Compilation Validation**: The `build()` method is called to validate scripts during the generation loop. Errors trigger revision cycles with the Scripter.

3. **Engine Identification**: The `getEngineName()` is included in system prompts so agents understand which engine they're targeting.

4. **Experience Playback**: Once generation is complete, `startExperience()` and `takeAction()` power the player's interaction with the finished experience.

## Configuration

The active IF engine is configured at the application level. Players may have preferences for specific engines (if multiple are supported), or the system may select an engine based on the type of experience being generated.

```dart
// Conceptual configuration structure
class ZForgeConfig {
  // ...existing fields...
  String defaultIfEngine; // e.g., "ink"
}
```

## Data Types

### BuildResult
```dart
class BuildResult {
  final Uint8List? output;
  final List<String> warnings;
  final List<String> errors;
  
  bool get success => output != null && errors.isEmpty;
}
```

### ActionResult
```dart
class ActionResult {
  final String text;
  final List<String>? choices;
  final bool isComplete;
}
```
