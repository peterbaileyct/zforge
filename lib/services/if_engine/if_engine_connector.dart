import 'dart:typed_data';

/// Result of compiling an IF script via [IfEngineConnector.build].
///
/// See docs/IF Engine Abstraction Layer.md — BuildResult.
class BuildResult {
  /// The compiled output, or null if compilation failed.
  final Uint8List? output;

  /// Compiler warnings (non-fatal).
  final List<String> warnings;

  /// Compiler errors (fatal; prevent execution).
  final List<String> errors;

  const BuildResult({
    required this.output,
    required this.warnings,
    required this.errors,
  });

  bool get success => output != null && errors.isEmpty;
}

/// Result of a single player action via [IfEngineConnector.takeAction].
///
/// See docs/IF Engine Abstraction Layer.md — ActionResult.
class ActionResult {
  /// The narrative text produced by this action.
  final String text;

  /// Available choices for the player, or null for parser-based engines.
  final List<String>? choices;

  /// Whether the experience has reached an ending.
  final bool isComplete;

  const ActionResult({
    required this.text,
    this.choices,
    required this.isComplete,
  });
}

/// Abstract interface for all supported IF engine connectors.
///
/// Implementations provide compilation and runtime execution for a specific
/// interactive fiction engine (e.g., ink, Inform 7, TADS).
///
/// See docs/IF Engine Abstraction Layer.md for the full specification.
/// Implemented by: lib/services/if_engine/ink_engine_connector.dart
abstract class IfEngineConnector {
  /// Returns the canonical name of the engine (e.g., "ink").
  String getEngineName();

  /// Returns the file extension for compiled output (e.g., ".ink.json").
  String getFileExtension();

  /// Returns engine-specific scripting guidance for the Scripter LLM agent.
  String getScriptPrompt();

  /// Compiles [script] source into a runnable format.
  Future<BuildResult> build(String script);

  /// Initializes a new playthrough from [compiledData] and returns opening text.
  Future<String> startExperience(Uint8List compiledData);

  /// Processes player [input] and returns the narrative result.
  /// For choice-based engines, [input] is the choice index as a string.
  Future<ActionResult> takeAction(String input);

  /// Serializes current playthrough state for persistence.
  Future<Uint8List> saveState();

  /// Restores a playthrough from [savedState] and returns current text.
  Future<String> restoreState(Uint8List savedState);
}
