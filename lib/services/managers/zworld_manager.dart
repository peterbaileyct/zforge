import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import '../../models/zworld.dart';
import '../../models/zforge_config.dart';

/// Event types broadcast by [ZWorldManager].
enum ZWorldEvent { created, deleted }

typedef ZWorldEventCallback = void Function(ZWorldEvent event, String worldName);

/// Singleton responsible for CRUD operations on [ZWorld] files (.zworld JSON).
///
/// On Mac/PC, worlds are stored in the configured [ZForgeConfig.zWorldFolderPath]
/// (default ~/zforge/worlds/). On mobile, they are stored in application
/// documents directory. Web storage is not yet supported.
///
/// Implemented in: lib/services/managers/zworld_manager.dart
class ZWorldManager {
  ZWorldManager._();
  static final ZWorldManager instance = ZWorldManager._();

  final List<ZWorldEventCallback> _listeners = [];

  void addListener(ZWorldEventCallback cb) => _listeners.add(cb);
  void removeListener(ZWorldEventCallback cb) => _listeners.remove(cb);

  void _notify(ZWorldEvent event, String worldName) {
    for (final cb in List.of(_listeners)) {
      cb(event, worldName);
    }
  }

  /// Returns the resolved storage directory for .zworld files.
  Future<Directory> resolveStorageDir(ZForgeConfig config) => _storageDir(config);

  Future<Directory> _storageDir(ZForgeConfig config) async {
    if (kIsWeb) throw UnsupportedError('Web ZWorld storage is not yet supported.');

    if (config.zWorldFolderPath != null) {
      final dir = Directory(config.zWorldFolderPath!);
      if (!dir.existsSync()) dir.createSync(recursive: true);
      return dir;
    }
    final appDir = await getApplicationDocumentsDirectory();
    final dir = Directory('${appDir.path}/zforge/worlds');
    if (!dir.existsSync()) dir.createSync(recursive: true);
    return dir;
  }

  String _fileName(String worldId) =>
      '${worldId.replaceAll(RegExp(r'[^\w\s-]'), '').replaceAll(' ', '_').toLowerCase()}.zworld';

  /// Creates and saves a [ZWorld]. Broadcasts [ZWorldEvent.created] unless
  /// [suppressEvent] is true.
  Future<void> create(ZWorld world, ZForgeConfig config,
      {bool suppressEvent = false}) async {
    final dir = await _storageDir(config);
    final file = File('${dir.path}/${_fileName(world.id)}');
    await file.writeAsString(jsonEncode(world.toJson()));
    if (!suppressEvent) _notify(ZWorldEvent.created, world.name);
  }

  /// Returns all saved [ZWorld] objects.
  Future<List<ZWorld>> listAll(ZForgeConfig config) async {
    if (kIsWeb) return [];
    try {
      final dir = await _storageDir(config);
      final files = dir.listSync().whereType<File>().where(
          (f) => f.path.endsWith('.zworld'));
      final worlds = <ZWorld>[];
      for (final f in files) {
        try {
          worlds.add(
              ZWorld.fromJson(jsonDecode(await f.readAsString()) as Map<String, dynamic>));
        } catch (_) {
          // Skip corrupted files silently.
        }
      }
      return worlds;
    } catch (_) {
      return [];
    }
  }

  /// Deletes the world file matching [worldId]. Broadcasts [ZWorldEvent.deleted].
  Future<void> delete(String worldId, ZForgeConfig config) async {
    final dir = await _storageDir(config);
    final file = File('${dir.path}/${_fileName(worldId)}');
    if (file.existsSync()) await file.delete();
    _notify(ZWorldEvent.deleted, worldId);
  }
}
