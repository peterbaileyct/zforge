# Ink Engine Connector

Implementation specification for the `InkEngineConnector`, which implements the [IF Engine Abstraction Layer](IF%20Engine%20Abstraction%20Layer.md) interface for the [ink](https://www.inklestudios.com/ink/) interactive fiction scripting language.

## Overview

The ink engine connector uses [inkjs](https://github.com/y-lohse/inkjs) (v2.4.0) running inside [flutter_js](https://pub.dev/packages/flutter_js) to provide both compilation and runtime execution. This approach allows Z-Forge to compile and run ink stories entirely client-side without requiring a server or native binaries.

## Dependencies

### Flutter Package
Add to `pubspec.yaml`:
```yaml
dependencies:
  flutter_js: ^0.8.1
```

### JavaScript Asset
The inkjs library is bundled as a Flutter asset:
- **File**: `assets/ink-full.js` (~249KB)
- **Version**: 2.4.0
- **Contents**: Complete inkjs distribution including compiler and runtime
- **Source**: https://unpkg.com/inkjs@2.4.0/dist/ink-full.js

The asset is registered in `pubspec.yaml`:
```yaml
flutter:
  assets:
    - assets/ink-full.js
```

## Implementation Location

```
lib/services/if_engine/
├── if_engine_connector.dart      # Abstract interface
└── ink_engine_connector.dart     # ink implementation
```

## InkEngineConnector Class

### Initialization

The connector requires async initialization to load the JavaScript runtime:

```dart
class InkEngineConnector implements IfEngineConnector {
  late JavascriptRuntime _jsRuntime;
  bool _initialized = false;
  
  /// Must be called before any other method.
  Future<void> initialize() async {
    if (_initialized) return;
    
    // Create JS runtime
    _jsRuntime = getJavascriptRuntime();
    
    // Load inkjs library from assets
    final inkJs = await rootBundle.loadString('assets/ink-full.js');
    _jsRuntime.evaluate(inkJs);
    
    _initialized = true;
  }
  
  void _ensureInitialized() {
    if (!_initialized) {
      throw StateError('InkEngineConnector.initialize() must be called first');
    }
  }
}
```

### Interface Implementation

#### getEngineName()
```dart
@override
String getEngineName() => 'ink';
```

#### getFileExtension()
```dart
@override
String getFileExtension() => '.ink.json';
```

#### getScriptPrompt()
```dart
@override
String getScriptPrompt() => '''
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

```dart
@override
Future<BuildResult> build(String script) async {
  _ensureInitialized();
  
  // Escape the script for JavaScript string literal
  final escapedScript = _escapeForJs(script);
  
  // Compile using inkjs Compiler
  final result = _jsRuntime.evaluate('''
    (function() {
      try {
        var compiler = new inkjs.Compiler("$escapedScript");
        var story = compiler.Compile();
        
        if (compiler.errors && compiler.errors.length > 0) {
          return JSON.stringify({
            success: false,
            errors: compiler.errors,
            warnings: compiler.warnings || []
          });
        }
        
        return JSON.stringify({
          success: true,
          json: story.ToJson(),
          warnings: compiler.warnings || []
        });
      } catch (e) {
        return JSON.stringify({
          success: false,
          errors: [e.toString()],
          warnings: []
        });
      }
    })()
  ''');
  
  final data = jsonDecode(result.stringResult) as Map<String, dynamic>;
  
  if (data['success'] == true) {
    final jsonString = data['json'] as String;
    return BuildResult(
      output: Uint8List.fromList(utf8.encode(jsonString)),
      warnings: List<String>.from(data['warnings'] ?? []),
      errors: [],
    );
  } else {
    return BuildResult(
      output: null,
      warnings: List<String>.from(data['warnings'] ?? []),
      errors: List<String>.from(data['errors'] ?? []),
    );
  }
}

String _escapeForJs(String input) {
  return input
      .replaceAll('\\', '\\\\')
      .replaceAll('"', '\\"')
      .replaceAll('\n', '\\n')
      .replaceAll('\r', '\\r')
      .replaceAll('\t', '\\t');
}
```

#### startExperience()

Starts a new playthrough by loading compiled JSON into an ink Story:

```dart
@override
Future<String> startExperience(Uint8List compiledData) async {
  _ensureInitialized();
  
  final jsonString = utf8.decode(compiledData);
  final escapedJson = _escapeForJs(jsonString);
  
  // Create new Story instance and store globally for subsequent calls
  _jsRuntime.evaluate('''
    window._inkStory = new inkjs.Story("$escapedJson");
  ''');
  
  // Get initial text
  return _continueStory();
}

String _continueStory() {
  final result = _jsRuntime.evaluate('''
    (function() {
      var story = window._inkStory;
      var text = "";
      
      while (story.canContinue) {
        text += story.Continue();
      }
      
      return text;
    })()
  ''');
  
  return result.stringResult.trim();
}
```

#### takeAction()

Processes player choice and returns the result:

```dart
@override
Future<ActionResult> takeAction(String input) async {
  _ensureInitialized();
  
  // Input is the choice index as a string (e.g., "0", "1", "2")
  final choiceIndex = int.tryParse(input);
  
  if (choiceIndex == null) {
    throw ArgumentError('ink requires numeric choice index, got: $input');
  }
  
  // Make the choice
  _jsRuntime.evaluate('''
    window._inkStory.ChooseChoiceIndex($choiceIndex);
  ''');
  
  // Continue and get resulting text
  final text = _continueStory();
  
  // Get current choices and completion state
  final stateResult = _jsRuntime.evaluate('''
    (function() {
      var story = window._inkStory;
      return JSON.stringify({
        choices: story.currentChoices.map(function(c) { return c.text; }),
        isComplete: !story.canContinue && story.currentChoices.length === 0
      });
    })()
  ''');
  
  final stateData = jsonDecode(stateResult.stringResult) as Map<String, dynamic>;
  final choices = List<String>.from(stateData['choices'] ?? []);
  final isComplete = stateData['isComplete'] as bool;
  
  return ActionResult(
    text: text,
    choices: choices.isEmpty ? null : choices,
    isComplete: isComplete,
  );
}
```

#### saveState()

Serializes the current Story state:

```dart
@override
Future<Uint8List> saveState() async {
  _ensureInitialized();
  
  final result = _jsRuntime.evaluate('''
    JSON.stringify(window._inkStory.state.ToJson());
  ''');
  
  return Uint8List.fromList(utf8.encode(result.stringResult));
}
```

#### restoreState()

Restores a previously saved Story state:

```dart
@override
Future<String> restoreState(Uint8List savedState) async {
  _ensureInitialized();
  
  final stateJson = utf8.decode(savedState);
  final escapedState = _escapeForJs(stateJson);
  
  _jsRuntime.evaluate('''
    window._inkStory.state.LoadJson("$escapedState");
  ''');
  
  // Return current text position (re-continue from restored state)
  return _continueStory();
}
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

1. After `startExperience()` or `takeAction()`, query available choices
2. Display choices to the player as numbered options or buttons
3. Pass the selected choice index (0-based) to `takeAction()`

Example flow:
```dart
// Start experience
final openingText = await connector.startExperience(compiledData);

// Get initial choices
final choices = await connector.getCurrentChoices(); // Helper method

// Player selects choice 1
final result = await connector.takeAction('1');

// result.text contains the narrative response
// result.choices contains the next set of choices (or null if none)
// result.isComplete indicates if the story has ended
```

## Helper Methods

Additional convenience methods (not part of the interface):

```dart
/// Get current available choices without making a selection.
Future<List<String>> getCurrentChoices() async {
  _ensureInitialized();
  
  final result = _jsRuntime.evaluate('''
    JSON.stringify(window._inkStory.currentChoices.map(function(c) { return c.text; }))
  ''');
  
  return List<String>.from(jsonDecode(result.stringResult));
}

/// Get current value of a story variable.
Future<dynamic> getVariable(String name) async {
  _ensureInitialized();
  
  final escapedName = _escapeForJs(name);
  final result = _jsRuntime.evaluate('''
    JSON.stringify(window._inkStory.variablesState["$escapedName"])
  ''');
  
  return jsonDecode(result.stringResult);
}

/// Set a story variable.
Future<void> setVariable(String name, dynamic value) async {
  _ensureInitialized();
  
  final escapedName = _escapeForJs(name);
  final valueJson = jsonEncode(value);
  
  _jsRuntime.evaluate('''
    window._inkStory.variablesState["$escapedName"] = $valueJson;
  ''');
}
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

Wrap `takeAction()` calls in try-catch and present errors appropriately to users.

## Platform Considerations

### flutter_js Availability
The `flutter_js` package supports:
- ✅ Android
- ✅ iOS
- ✅ macOS
- ✅ Windows
- ✅ Linux
- ⚠️ Web: Uses browser's JavaScript engine directly

### Performance
- Initial JS runtime creation: ~100-200ms
- inkjs library load: ~50-100ms
- Compilation: Depends on script complexity, typically <1s
- Runtime operations: <10ms per call

### Memory
- Each `InkEngineConnector` instance maintains its own JS runtime
- Consider reusing instances across multiple experience loads
- Call `dispose()` when done to release JS runtime resources

```dart
void dispose() {
  if (_initialized) {
    _jsRuntime.dispose();
    _initialized = false;
  }
}
```

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
