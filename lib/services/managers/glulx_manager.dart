/// Singleton stub for Glulx (.gblorb) experience management.
/// Full implementation is deferred to Phase 2 (Inform/Glulx generation).
///
/// Implemented in: lib/services/managers/glulx_manager.dart
class GlulxManager {
  GlulxManager._();
  static final GlulxManager instance = GlulxManager._();

  /// Returns true if at least one .gblorb experience file exists.
  Future<bool> hasExperiences() async => false; // Phase 2

  /// Returns true if at least one in-progress save exists.
  Future<bool> hasSaves() async => false; // Phase 2
}
