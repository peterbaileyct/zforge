import 'dart:convert';
import 'package:http/http.dart' as http;
import '../../models/zforge_secure_config.dart';
import 'llm_connector.dart';

/// Concrete [LlmConnector] implementation for OpenAI (ChatGPT).
/// Uses the Chat Completions API with function calling for tool invocation.
///
/// Configuration keys: ["api_key"]
///
/// See docs/LLM Abstraction Layer.md for the abstract specification.
/// Implemented in: lib/services/llm/openai_connector.dart
class OpenAiConnector implements LlmConnector {
  static const String _name = 'ChatGPT';
  static const String _baseUrl = 'https://api.openai.com/v1';
  static const String _model = 'gpt-4o';

  String? _apiKey;

  @override
  String get connectorName => _name;

  @override
  List<String> get configKeys => ['api_key'];

  @override
  bool get isConfigured => _apiKey != null && _apiKey!.isNotEmpty;

  @override
  void loadConfiguration(LlmConnectorConfiguration config) {
    _apiKey = config.values['api_key'];
  }

  @override
  Future<String?> validateConfiguration() async {
    if (!isConfigured) return 'API key is not set.';
    try {
      final response = await http.get(
        Uri.parse('$_baseUrl/models'),
        headers: _headers,
      );
      if (response.statusCode == 200) return null;
      if (response.statusCode == 401) return 'Invalid API key.';
      return 'Validation failed (HTTP ${response.statusCode}).';
    } catch (e) {
      return 'Could not connect to OpenAI: $e';
    }
  }

  @override
  Future<LlmResult> execute(LlmQuery query) async {
    final messages = [
      {'role': 'system', 'content': query.systemMessage},
      {'role': 'user', 'content': query.actionMessage},
    ];

    final body = <String, dynamic>{
      'model': _model,
      'messages': messages,
    };

    if (query.tool != null) {
      body['tools'] = [_toolToOpenAiFunction(query.tool!)];
      body['tool_choice'] = {'type': 'function', 'function': {'name': query.tool!.name}};
    } else if (query.availableTools.isNotEmpty) {
      body['tools'] =
          query.availableTools.map(_toolToOpenAiFunction).toList();
      body['tool_choice'] = 'auto';
    }

    final response = await http.post(
      Uri.parse('$_baseUrl/chat/completions'),
      headers: _headers,
      body: jsonEncode(body),
    );

    if (response.statusCode != 200) {
      final errBody = jsonDecode(response.body);
      throw Exception(
          'OpenAI error ${response.statusCode}: ${errBody['error']?['message'] ?? response.body}');
    }

    final json = jsonDecode(response.body) as Map<String, dynamic>;
    final choice = (json['choices'] as List).first as Map<String, dynamic>;
    final message = choice['message'] as Map<String, dynamic>;

    final toolCalls = message['tool_calls'] as List?;
    if (toolCalls != null && toolCalls.isNotEmpty) {
      final call = toolCalls.first as Map<String, dynamic>;
      final fnName = call['function']['name'] as String;
      final args = jsonDecode(call['function']['arguments'] as String) as Map<String, dynamic>;
      return LlmResult(toolName: fnName, toolCallArguments: args);
    }

    return LlmResult(text: message['content'] as String?);
  }

  Map<String, String> get _headers => {
        'Authorization': 'Bearer $_apiKey',
        'Content-Type': 'application/json',
      };

  Map<String, dynamic> _toolToOpenAiFunction(LlmTool tool) => {
        'type': 'function',
        'function': {
          'name': tool.name,
          'description': tool.description,
          'parameters': tool.parametersSchema,
        },
      };
}
