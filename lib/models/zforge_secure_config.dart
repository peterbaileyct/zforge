// Secure configuration stored in platform keychain/secure storage.
// Contains LLM connector credentials.
// See docs/LLM Abstraction Layer.md and docs/User Experience.md.

/// A set of key/value pairs required to configure a specific LLM connector.
class LlmConnectorConfiguration {
  /// Identifies which LlmConnector this configuration belongs to.
  final String connectorName;

  /// Arbitrary key/value credential pairs (e.g. {"api_key": "sk-..."}).
  final Map<String, String> values;

  const LlmConnectorConfiguration({
    required this.connectorName,
    required this.values,
  });

  factory LlmConnectorConfiguration.fromJson(Map<String, dynamic> json) =>
      LlmConnectorConfiguration(
        connectorName: json['connector_name'] as String,
        values: Map<String, String>.from(json['values'] as Map),
      );

  Map<String, dynamic> toJson() => {
        'connector_name': connectorName,
        'values': values,
      };

  LlmConnectorConfiguration copyWithValue(String key, String value) =>
      LlmConnectorConfiguration(
        connectorName: connectorName,
        values: {...values, key: value},
      );
}

/// Secure app configuration holding credentials for all LLM connectors,
/// keyed by connector name.
class ZForgeSecureConfig {
  final Map<String, LlmConnectorConfiguration> connectors;

  const ZForgeSecureConfig({this.connectors = const {}});

  factory ZForgeSecureConfig.fromJson(Map<String, dynamic> json) {
    final connectors = <String, LlmConnectorConfiguration>{};
    for (final entry in json.entries) {
      connectors[entry.key] = LlmConnectorConfiguration.fromJson(
          entry.value as Map<String, dynamic>);
    }
    return ZForgeSecureConfig(connectors: connectors);
  }

  Map<String, dynamic> toJson() =>
      {for (final e in connectors.entries) e.key: e.value.toJson()};

  ZForgeSecureConfig withConnector(LlmConnectorConfiguration config) =>
      ZForgeSecureConfig(
        connectors: {...connectors, config.connectorName: config},
      );
}
