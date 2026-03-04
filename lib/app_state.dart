import 'package:flutter/foundation.dart';
import 'models/zforge_config.dart';
import 'models/zforge_secure_config.dart';
import 'models/zworld.dart';
import 'services/config_service.dart';
import 'services/secure_config_service.dart';
import 'services/llm/llm_connector.dart';
import 'services/llm/openai_connector.dart';
import 'services/managers/zworld_manager.dart';
import 'services/managers/experience_manager.dart';
import 'services/if_engine/ink_engine_connector.dart';

/// Central application state, exposed to the widget tree via [Provider].
///
/// Responsible for:
/// - Loading and persisting [ZForgeConfig] and [ZForgeSecureConfig].
/// - Initializing and exposing the active [LlmConnector].
/// - Tracking the list of available [ZWorld] objects.
/// - Providing the [InkEngineConnector] and [ExperienceManager] for
///   experience generation and gameplay.
///
/// Implemented in: lib/app_state.dart
class AppState extends ChangeNotifier {
  ZForgeConfig _config = const ZForgeConfig();
  ZForgeSecureConfig _secureConfig = const ZForgeSecureConfig();
  List<ZWorld> _worlds = [];
  bool _initialized = false;
  String? _initError;

  ZForgeConfig get config => _config;
  ZForgeSecureConfig get secureConfig => _secureConfig;
  List<ZWorld> get worlds => List.unmodifiable(_worlds);
  bool get initialized => _initialized;
  String? get initError => _initError;

  final LlmConnector _connector = OpenAiConnector();
  LlmConnector get connector => _connector;

  final InkEngineConnector _ifEngine = InkEngineConnector();
  InkEngineConnector get ifEngine => _ifEngine;

  bool get llmConfigured => _connector.isConfigured;

  /// Loads config, secure config, and world list. Called at app startup.
  Future<void> initialize() async {
    try {
      _config = await ConfigService.instance.load();
      _secureConfig = await SecureConfigService.instance.load();

      final connectorConfig =
          _secureConfig.connectors[_connector.connectorName];
      if (connectorConfig != null) {
        _connector.loadConfiguration(connectorConfig);
      }

      await _ifEngine.initialize();

      ZWorldManager.instance.addListener(_onWorldEvent);
      _worlds = await ZWorldManager.instance.listAll(_config);
      _initialized = true;
    } catch (e) {
      _initError = e.toString();
      _initialized = true;
    }
    notifyListeners();
  }

  void _onWorldEvent(ZWorldEvent event, String worldName) async {
    _worlds = await ZWorldManager.instance.listAll(_config);
    notifyListeners();
  }

  /// Saves updated LLM credentials and reloads connector config.
  Future<String?> saveLlmConfig(Map<String, String> values) async {
    final connConfig = LlmConnectorConfiguration(
      connectorName: _connector.connectorName,
      values: values,
    );
    _connector.loadConfiguration(connConfig);
    final error = await _connector.validateConfiguration();
    if (error != null) return error;

    _secureConfig = _secureConfig.withConnector(connConfig);
    await SecureConfigService.instance.save(_secureConfig);
    notifyListeners();
    return null;
  }

  /// Saves updated [ZForgeConfig].
  Future<void> saveConfig(ZForgeConfig config) async {
    _config = config;
    await ConfigService.instance.save(config);
    notifyListeners();
  }

  Future<bool> hasExperiences() =>
      ExperienceManager.instance.hasExperiences(_config);
  Future<bool> hasSaves() =>
      ExperienceManager.instance.hasSaves(_config);

  @override
  void dispose() {
    ZWorldManager.instance.removeListener(_onWorldEvent);
    _ifEngine.dispose();
    super.dispose();
  }
}
