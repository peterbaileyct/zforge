import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../models/zforge_secure_config.dart';

const _storageKey = 'zforge_secure_config';

/// Persists [ZForgeSecureConfig] (LLM credentials) using flutter_secure_storage,
/// which delegates to the platform keychain/keystore.
///
/// macOS note: We use a custom account name and set groupId to null to avoid
/// requiring keychain-access-groups entitlement. The synchronizable option is
/// disabled to keep data local. For debug builds, the keychain may still prompt
/// on first access after rebuild - click "Always Allow" to prevent future prompts.
///
/// Implemented in: lib/services/secure_config_service.dart
class SecureConfigService {
  static const SecureConfigService _instance = SecureConfigService._();
  const SecureConfigService._();
  static SecureConfigService get instance => _instance;

  static FlutterSecureStorage get _storage {
    if (!kIsWeb && Platform.isMacOS) {
      return const FlutterSecureStorage(
        mOptions: MacOsOptions(
          // Use a consistent account name tied to our app
          accountName: 'com.zforge.credentials',
          // Use legacy file-based keychain to avoid keychain-access-groups entitlement
          useDataProtectionKeyChain: false,
          // No group ID - we don't need to share across apps
          groupId: null,
          // Don't sync to iCloud - keep credentials local
          synchronizable: false,
          // Allow access when device is unlocked
          accessibility: KeychainAccessibility.unlocked,
        ),
      );
    }
    return const FlutterSecureStorage();
  }

  Future<ZForgeSecureConfig> load() async {
    try {
      final raw = await _storage.read(key: _storageKey);
      if (raw == null) return const ZForgeSecureConfig();
      return ZForgeSecureConfig.fromJson(
          jsonDecode(raw) as Map<String, dynamic>);
    } catch (_) {
      return const ZForgeSecureConfig();
    }
  }

  Future<void> save(ZForgeSecureConfig config) async {
    await _storage.write(
        key: _storageKey, value: jsonEncode(config.toJson()));
  }
}
