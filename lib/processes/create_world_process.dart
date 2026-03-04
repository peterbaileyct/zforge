import 'package:flutter/foundation.dart';
import '../models/zworld.dart';
import '../models/zforge_config.dart';
import '../services/llm/llm_connector.dart';
import '../services/mcp/zforge_mcp_server.dart';

/// Status of a [CreateWorldProcess].
enum CreateWorldStatus {
  idle,
  validatingInput,
  generatingWorld,
  saving,
  success,
  inputRejected,
  failed,
}

/// Manages the multi-step agentic workflow for creating a [ZWorld] from
/// plain text. Steps:
///
/// 1. Validate the input text using the LLM (up to [maxValidationAttempts]).
/// 2. If valid, prompt the LLM to generate a ZWorld via MCP [ZForgeMcpServer].
/// 3. Save the world via [ZWorldManager] (done inside [ZForgeMcpServer]).
///
/// See docs/World Generation.md for the full workflow specification.
/// Implemented in: lib/processes/create_world_process.dart
class CreateWorldProcess extends ChangeNotifier {
  static const int maxValidationAttempts = 5;

  final LlmConnector _connector;
  final ZForgeConfig _config;

  CreateWorldProcess({
    required LlmConnector connector,
    required ZForgeConfig config,
  })  : _connector = connector,
        _config = config;

  CreateWorldStatus _status = CreateWorldStatus.idle;
  CreateWorldStatus get status => _status;

  /// null = unknown, true = valid, false = invalid
  bool? _inputValid;
  bool? get inputValid => _inputValid;

  ZWorld? _world;
  ZWorld? get world => _world;

  String? _errorMessage;
  String? get errorMessage => _errorMessage;

  int _validationAttempts = 0;
  int get validationAttempts => _validationAttempts;

  bool get isRunning =>
      _status == CreateWorldStatus.validatingInput ||
      _status == CreateWorldStatus.generatingWorld ||
      _status == CreateWorldStatus.saving;

  /// Starts the world creation pipeline for [inputText].
  Future<void> run(String inputText) async {
    _status = CreateWorldStatus.validatingInput;
    _inputValid = null;
    _world = null;
    _errorMessage = null;
    _validationAttempts = 0;
    notifyListeners();

    // Step 1: Validate input (up to maxValidationAttempts).
    await _validateInput(inputText);

    if (_inputValid != true) {
      // Failure path: ask LLM to explain the rejection.
      await _explainRejection(inputText);
      _status = CreateWorldStatus.inputRejected;
      notifyListeners();
      return;
    }

    // Step 2: Generate the ZWorld.
    _status = CreateWorldStatus.generatingWorld;
    notifyListeners();
    await _generateWorld(inputText);
  }

  /// Validates [inputText] as a fictional world description using the LLM.
  /// Retries up to [maxValidationAttempts] times.
  Future<void> _validateInput(String inputText) async {
    for (int attempt = 0; attempt < maxValidationAttempts; attempt++) {
      _validationAttempts = attempt + 1;
      _inputValid = null;
      notifyListeners();

      try {
        final result = await _connector.execute(LlmQuery(
          systemMessage:
              'You are a literature editor. You are to determine whether the '
              'following is a clear description of a fictional world, listing '
              'characters and their relationships with one another, locations, '
              'and events.',
          actionMessage:
              'Evaluate the given world description. Call the validate_input '
              'function with valid=true if it is a sufficiently clear fictional '
              'world description, or valid=false if it is not.\n\n'
              'World description:\n$inputText',
          tool: _validateTool,
        ));

        if (result.hasToolCall &&
            result.toolName == 'validate_input' &&
            result.toolCallArguments != null) {
          final valid = result.toolCallArguments!['valid'];
          _inputValid = valid == true || valid == 'true';
          if (_inputValid == true) return;
        }
      } catch (e) {
        _errorMessage = e.toString();
      }
    }
    // If we exhausted attempts without a true, mark invalid.
    _inputValid ??= false;
  }

  /// Asks the LLM to explain why the input was rejected, storing the
  /// explanation in [errorMessage].
  Future<void> _explainRejection(String inputText) async {
    try {
      final result = await _connector.execute(LlmQuery(
        systemMessage:
            'You are a literature editor reviewing a world description intended '
            'for use in an interactive fiction system.',
        actionMessage:
            'The following text was rejected as a suitable world description. '
            'Briefly explain to the user why it is inadequate or inappropriate '
            'and what they could do to improve it.\n\nText:\n$inputText',
      ));
      _errorMessage = result.text ??
          'Your description was not recognised as a valid fictional world. '
              'Please add more details about characters, locations, and events.';
    } catch (_) {
      _errorMessage =
          'Your description was not recognised as a valid fictional world. '
          'Please add more details about characters, locations, and events.';
    }
  }

  /// Prompts the LLM to create a ZWorld via MCP and saves it.
  Future<void> _generateWorld(String inputText) async {
    try {
      final result = await _connector.execute(LlmQuery(
        systemMessage:
            'You are a designer for an interactive fiction system. ZWorlds, '
            'used as the basis of your interactive fiction experiences, consist '
            'of: a name; locations (nestable); characters with IDs, multiple '
            'names (each with optional context), and history; relationships '
            'between characters; and world events with dates. '
            'Create a ZWorld from the following description of a fictional world.',
        actionMessage:
            'Build the specified ZWorld from this description and call '
            'create_zworld with all fields populated.\n\nDescription:\n$inputText',
        tool: ZForgeMcpServer.createZWorldTool,
      ));

      if (!result.hasToolCall || result.toolName != 'create_zworld') {
        throw Exception('LLM did not call the create_zworld tool.');
      }

      _status = CreateWorldStatus.saving;
      notifyListeners();

      _world = await ZForgeMcpServer.instance
          .dispatch('create_zworld', result.toolCallArguments!, _config);

      _status = CreateWorldStatus.success;
      notifyListeners();
    } catch (e) {
      _errorMessage = e.toString();
      _status = CreateWorldStatus.failed;
      notifyListeners();
    }
  }

  /// Tool definition used for input validation (inline; not routed via MCP).
  static final LlmTool _validateTool = LlmTool(
    name: 'validate_input',
    description: 'Reports whether the given text is a valid fictional world description.',
    parametersSchema: {
      'type': 'object',
      'required': ['valid'],
      'properties': {
        'valid': {
          'type': 'boolean',
          'description':
              'true if the text clearly describes a fictional world; false otherwise.',
        },
      },
    },
  );
}
