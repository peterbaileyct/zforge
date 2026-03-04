import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_js/flutter_js.dart';
import 'if_engine_connector.dart';

/// ink engine implementation of [IfEngineConnector].
///
/// Uses inkjs (v2.4.0) running inside flutter_js for both compilation and
/// runtime execution, entirely client-side.
///
/// Requires [initialize] to be called before any other method.
/// See docs/Ink Engine Connector.md for the full specification.
/// Implemented in: lib/services/if_engine/ink_engine_connector.dart
class InkEngineConnector implements IfEngineConnector {
  late JavascriptRuntime _jsRuntime;
  bool _initialized = false;

  /// Loads the inkjs library from assets into the JS runtime.
  /// Must be called before any other method.
  Future<void> initialize() async {
    if (_initialized) return;
    _jsRuntime = getJavascriptRuntime();
    final inkJs = await rootBundle.loadString('assets/ink-full.js');
    _jsRuntime.evaluate(inkJs);
    // Create a global storage object for the ink story
    _jsRuntime.evaluate('var _inkStory = null;');
    _initialized = true;
  }

  void _ensureInitialized() {
    if (!_initialized) {
      throw StateError('InkEngineConnector.initialize() must be called first');
    }
  }

  @override
  String getEngineName() => 'ink';

  @override
  String getFileExtension() => '.ink.json';

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

  @override
  Future<BuildResult> build(String script) async {
    _ensureInitialized();
    final escapedScript = _escapeForJs(script);
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
      return BuildResult(
        output: Uint8List.fromList(utf8.encode(data['json'] as String)),
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

  @override
  Future<String> startExperience(Uint8List compiledData) async {
    _ensureInitialized();
    final jsonString = utf8.decode(compiledData);
    debugPrint('[InkEngine] startExperience: JSON length=${jsonString.length}');
    final escapedJson = _escapeForJs(jsonString);
    final createResult = _jsRuntime.evaluate('''
      (function() {
        try {
          _inkStory = new inkjs.Story("$escapedJson");
          return JSON.stringify({ success: true });
        } catch (e) {
          return JSON.stringify({ success: false, error: e.toString() });
        }
      })()
    ''');
    debugPrint('[InkEngine] Create story result: ${createResult.stringResult}');
    final createData = jsonDecode(createResult.stringResult) as Map<String, dynamic>;
    if (createData['success'] != true) {
      throw Exception('Failed to create ink story: ${createData['error']}');
    }
    
    // Try to continue story; if no content, try jumping to common start knots
    final tryResult = _jsRuntime.evaluate('''
      (function() {
        var story = _inkStory;
        var text = "";
        
        // First, try to get content from where the story starts
        while (story.canContinue) {
          text += story.Continue();
        }
        
        // If we got content or choices, we're good
        if (text.trim().length > 0 || story.currentChoices.length > 0) {
          return JSON.stringify({ success: true, text: text, method: "direct" });
        }
        
        // No content at root - try jumping to common starting knot names
        var startKnots = ["opening", "start", "begin", "intro", "main"];
        for (var i = 0; i < startKnots.length; i++) {
          try {
            var container = story.KnotContainerWithName(startKnots[i]);
            if (container) {
              story.ChoosePathString(startKnots[i]);
              text = "";
              while (story.canContinue) {
                text += story.Continue();
              }
              if (text.trim().length > 0 || story.currentChoices.length > 0) {
                return JSON.stringify({ success: true, text: text, method: "jumped", knot: startKnots[i] });
              }
            }
          } catch (e) {
            // Continue trying other knots
          }
        }
        
        return JSON.stringify({ success: false, error: "No playable content found in story" });
      })()
    ''');
    debugPrint('[InkEngine] Try result: ${tryResult.stringResult}');
    
    final tryData = jsonDecode(tryResult.stringResult) as Map<String, dynamic>;
    if (tryData['success'] != true) {
      throw Exception(tryData['error'] ?? 'Failed to start story');
    }
    return (tryData['text'] as String? ?? '').trim();
  }

  @override
  Future<ActionResult> takeAction(String input) async {
    _ensureInitialized();
    final choiceIndex = int.tryParse(input);
    if (choiceIndex == null) {
      throw ArgumentError('ink requires numeric choice index, got: $input');
    }
    _jsRuntime.evaluate('''
      _inkStory.ChooseChoiceIndex($choiceIndex);
    ''');
    final text = _continueStory();
    final stateResult = _jsRuntime.evaluate('''
      (function() {
        var story = _inkStory;
        return JSON.stringify({
          choices: story.currentChoices.map(function(c) { return c.text; }),
          isComplete: !story.canContinue && story.currentChoices.length === 0
        });
      })()
    ''');
    final stateData =
        jsonDecode(stateResult.stringResult) as Map<String, dynamic>;
    final choices = List<String>.from(stateData['choices'] ?? []);
    return ActionResult(
      text: text,
      choices: choices.isEmpty ? null : choices,
      isComplete: stateData['isComplete'] as bool,
    );
  }

  @override
  Future<Uint8List> saveState() async {
    _ensureInitialized();
    final result = _jsRuntime.evaluate('''
      JSON.stringify(_inkStory.state.ToJson());
    ''');
    return Uint8List.fromList(utf8.encode(result.stringResult));
  }

  @override
  Future<String> restoreState(Uint8List savedState) async {
    _ensureInitialized();
    final stateJson = utf8.decode(savedState);
    final escapedState = _escapeForJs(stateJson);
    _jsRuntime.evaluate('''
      _inkStory.state.LoadJson("$escapedState");
    ''');
    return _continueStory();
  }

  /// Returns available choices without advancing the story.
  Future<List<String>> getCurrentChoices() async {
    _ensureInitialized();
    final result = _jsRuntime.evaluate('''
      (function() {
        try {
          if (!_inkStory) {
            return JSON.stringify({ success: false, error: "Story not initialized" });
          }
          var choices = _inkStory.currentChoices.map(function(c) { return c.text; });
          return JSON.stringify({ success: true, choices: choices });
        } catch (e) {
          return JSON.stringify({ success: false, error: e.toString() });
        }
      })()
    ''');
    final data = jsonDecode(result.stringResult) as Map<String, dynamic>;
    if (data['success'] != true) {
      throw Exception('Failed to get choices: ${data['error']}');
    }
    return List<String>.from(data['choices'] as List);
  }

  /// Reads the current value of a story variable.
  Future<dynamic> getVariable(String name) async {
    _ensureInitialized();
    final escapedName = _escapeForJs(name);
    final result = _jsRuntime.evaluate('''
      JSON.stringify(_inkStory.variablesState["$escapedName"])
    ''');
    return jsonDecode(result.stringResult);
  }

  /// Sets a story variable to [value].
  Future<void> setVariable(String name, dynamic value) async {
    _ensureInitialized();
    final escapedName = _escapeForJs(name);
    final valueJson = jsonEncode(value);
    _jsRuntime.evaluate('''
      _inkStory.variablesState["$escapedName"] = $valueJson;
    ''');
  }

  /// Releases the JS runtime. Call when done with this connector.
  void dispose() {
    if (_initialized) {
      _jsRuntime.dispose();
      _initialized = false;
    }
  }

  String _continueStory() {
    final result = _jsRuntime.evaluate('''
      (function() {
        try {
          var story = _inkStory;
          if (!story) {
            return JSON.stringify({ success: false, error: "Story not initialized" });
          }
          var text = "";
          while (story.canContinue) {
            text += story.Continue();
          }
          return JSON.stringify({ success: true, text: text, canContinue: story.canContinue, choicesCount: story.currentChoices.length });
        } catch (e) {
          return JSON.stringify({ success: false, error: e.toString() });
        }
      })()
    ''');
    debugPrint('[InkEngine] _continueStory result: ${result.stringResult}');
    final data = jsonDecode(result.stringResult) as Map<String, dynamic>;
    if (data['success'] != true) {
      throw Exception('Failed to continue story: ${data['error']}');
    }
    return (data['text'] as String? ?? '').trim();
  }

  String _escapeForJs(String input) {
    return input
        .replaceAll('\\', '\\\\')
        .replaceAll('"', '\\"')
        .replaceAll('\n', '\\n')
        .replaceAll('\r', '\\r')
        .replaceAll('\t', '\\t');
  }
}
