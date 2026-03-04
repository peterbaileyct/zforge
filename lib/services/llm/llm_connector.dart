import '../../models/zforge_secure_config.dart';

/// Describes a single tool that the LLM may call in response to a query.
class LlmTool {
  /// Machine-readable tool name (e.g. "create_zworld").
  final String name;

  /// Human/LLM-readable description of what the tool does.
  final String description;

  /// JSON Schema object describing the tool's parameters.
  final Map<String, dynamic> parametersSchema;

  const LlmTool({
    required this.name,
    required this.description,
    required this.parametersSchema,
  });
}

/// Encapsulates a single LLM request.
class LlmQuery {
  /// Sets the LLM's role and provides contextual background.
  final String systemMessage;

  /// The specific action the LLM should perform right now.
  final String actionMessage;

  /// If non-null, the LLM is required to invoke this specific tool.
  final LlmTool? tool;

  /// If non-empty, these tools are available for the LLM to choose from
  /// (without forcing any specific one). Ignored if [tool] is set.
  final List<LlmTool> availableTools;

  const LlmQuery({
    required this.systemMessage,
    required this.actionMessage,
    this.tool,
    this.availableTools = const [],
  });
}

/// Result of an [LlmConnector.execute] call.
class LlmResult {
  /// The LLM's text reply (if any).
  final String? text;

  /// Tool call arguments if the LLM invoked a tool (keyed by parameter name).
  final Map<String, dynamic>? toolCallArguments;

  /// Name of the tool called, if applicable.
  final String? toolName;

  const LlmResult({this.text, this.toolCallArguments, this.toolName});

  bool get hasToolCall => toolCallArguments != null;
}

/// Abstract base class for all Z-Forge LLM integrations.
/// Concrete implementations must supply credentials, validate them,
/// and execute queries with optional tool calling.
///
/// See docs/LLM Abstraction Layer.md for full specification.
/// Implemented by: lib/services/llm/openai_connector.dart
abstract class LlmConnector {
  /// Human-readable name of this LLM/connector (e.g. "ChatGPT").
  String get connectorName;

  /// Ordered list of configuration key names required by this connector
  /// (e.g. ["api_key"]).
  List<String> get configKeys;

  /// Loads credentials from [config] into this connector's internal state.
  void loadConfiguration(LlmConnectorConfiguration config);

  /// Validates that the current configuration is correct (e.g. by making a
  /// lightweight API call). Returns null on success or an error message.
  Future<String?> validateConfiguration();

  /// Executes an LLM query and returns the result.
  Future<LlmResult> execute(LlmQuery query);

  /// Returns true if all required config keys have non-empty values.
  bool get isConfigured;
}
