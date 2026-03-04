import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/zforge_config.dart';

const _prefKey = 'zforge_config';

/// Persists [ZForgeConfig] using shared_preferences.
/// On desktop platforms (macOS, Windows, Linux), provides default folder paths
/// under ~/zforge/. On mobile/web, folder paths are null.
///
/// Implemented in: lib/services/config_service.dart
class ConfigService {
  static const ConfigService _instance = ConfigService._();
  const ConfigService._();
  static ConfigService get instance => _instance;

  Future<ZForgeConfig> load() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_prefKey);
    if (raw == null) return await _defaultConfig();
    try {
      return ZForgeConfig.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } catch (_) {
      return await _defaultConfig();
    }
  }

  Future<void> save(ZForgeConfig config) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefKey, jsonEncode(config.toJson()));
  }

  Future<ZForgeConfig> _defaultConfig() async {
    String? worldFolder;
    String? experienceFolder;

    if (!kIsWeb && (Platform.isMacOS || Platform.isWindows || Platform.isLinux)) {
      final home = Platform.environment['HOME'] ??
          Platform.environment['USERPROFILE'] ??
          (await getApplicationDocumentsDirectory()).path;
      worldFolder = '$home/zforge/worlds';
      experienceFolder = '$home/zforge/experiences';
    }

    return ZForgeConfig(
      zWorldFolderPath: worldFolder,
      experienceFolderPath: experienceFolder,
    );
  }
}
