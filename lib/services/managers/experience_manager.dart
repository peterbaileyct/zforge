import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import '../../models/zworld.dart';
import '../../models/zforge_config.dart';

/// A saved, playable interactive fiction experience.
///
/// Experiences are stored under {experienceFolderPath}/{zworld.id}/ on desktop
/// or in application documents on mobile. The file extension identifies the
/// IF engine that can play the experience (e.g., ".ink.json").
class Experience {
  final String zworldId;
  final String name;
  final String engineExtension;
  final String filePath;

  const Experience({
    required this.zworldId,
    required this.name,
    required this.engineExtension,
    required this.filePath,
  });

  String get saveFilePath => filePath.replaceAll(engineExtension, '.save');
}

/// Singleton responsible for CRUD operations on compiled IF experience files.
///
/// Experiences are organized by ZWorld:
///   {experienceFolderPath}/{zworld.id}/{name}{engineExtension}
/// Saved progress is stored alongside:
///   {experienceFolderPath}/{zworld.id}/{name}.save
///
/// See docs/User Experience.md — ExperienceManager section.
/// Implemented in: lib/services/managers/experience_manager.dart
class ExperienceManager {
  ExperienceManager._();
  static final ExperienceManager instance = ExperienceManager._();

  /// Returns the root experience storage directory.
  Future<Directory> _rootDir(ZForgeConfig config) async {
    if (kIsWeb) throw UnsupportedError('Web experience storage is not yet supported.');
    final base = config.experienceFolderPath;
    if (base != null) {
      final dir = Directory(base);
      if (!dir.existsSync()) dir.createSync(recursive: true);
      return dir;
    }
    final appDir = await getApplicationDocumentsDirectory();
    final dir = Directory('${appDir.path}/zforge/experiences');
    if (!dir.existsSync()) dir.createSync(recursive: true);
    return dir;
  }

  Future<Directory> _worldDir(ZForgeConfig config, String zworldId) async {
    final root = await _rootDir(config);
    final dir = Directory('${root.path}/$zworldId');
    if (!dir.existsSync()) dir.createSync(recursive: true);
    return dir;
  }

  /// Saves a compiled experience to storage.
  Future<Experience> save(
    ZWorld world,
    String name,
    Uint8List compiledData,
    String engineExtension,
    ZForgeConfig config,
  ) async {
    final dir = await _worldDir(config, world.id);
    final safeName =
        name.replaceAll(RegExp(r'[^\w\s-]'), '').replaceAll(' ', '-').toLowerCase();
    final filePath = '${dir.path}/$safeName$engineExtension';
    await File(filePath).writeAsBytes(compiledData);
    return Experience(
      zworldId: world.id,
      name: safeName,
      engineExtension: engineExtension,
      filePath: filePath,
    );
  }

  /// Returns all saved experiences across all worlds.
  Future<List<Experience>> listAll(ZForgeConfig config) async {
    if (kIsWeb) return [];
    try {
      final root = await _rootDir(config);
      final experiences = <Experience>[];
      for (final worldDir
          in root.listSync().whereType<Directory>()) {
        final zworldId = worldDir.path.split('/').last;
        for (final file in worldDir.listSync().whereType<File>()) {
          final path = file.path;
          if (path.endsWith('.save')) continue;
          final fileName = path.split('/').last;
          final dotIdx = fileName.indexOf('.');
          if (dotIdx < 0) continue;
          final name = fileName.substring(0, dotIdx);
          final ext = fileName.substring(dotIdx);
          experiences.add(Experience(
            zworldId: zworldId,
            name: name,
            engineExtension: ext,
            filePath: path,
          ));
        }
      }
      return experiences;
    } catch (_) {
      return [];
    }
  }

  /// Returns all experiences for a specific world.
  Future<List<Experience>> listForWorld(
      ZForgeConfig config, String zworldId) async {
    final all = await listAll(config);
    return all.where((e) => e.zworldId == zworldId).toList();
  }

  /// Deletes an experience and its save file.
  Future<void> delete(Experience experience) async {
    final file = File(experience.filePath);
    if (file.existsSync()) await file.delete();
    final save = File(experience.saveFilePath);
    if (save.existsSync()) await save.delete();
  }

  /// Returns true if at least one experience file exists.
  Future<bool> hasExperiences(ZForgeConfig config) async {
    if (kIsWeb) return false;
    return (await listAll(config)).isNotEmpty;
  }

  /// Saves playthrough progress for an experience.
  Future<void> saveProgress(Experience experience, Uint8List stateBytes) async {
    await File(experience.saveFilePath).writeAsBytes(stateBytes);
  }

  /// Loads saved progress for an experience, or null if none exists.
  Future<Uint8List?> loadProgress(Experience experience) async {
    final file = File(experience.saveFilePath);
    if (!file.existsSync()) return null;
    return file.readAsBytes();
  }

  /// Returns true if at least one experience has saved progress.
  Future<bool> hasSaves(ZForgeConfig config) async {
    if (kIsWeb) return false;
    try {
      final root = await _rootDir(config);
      for (final worldDir in root.listSync().whereType<Directory>()) {
        for (final file in worldDir.listSync().whereType<File>()) {
          if (file.path.endsWith('.save')) return true;
        }
      }
      return false;
    } catch (_) {
      return false;
    }
  }

  /// Loads the compiled data for an experience.
  Future<Uint8List> loadCompiledData(Experience experience) async {
    return File(experience.filePath).readAsBytes();
  }
}
