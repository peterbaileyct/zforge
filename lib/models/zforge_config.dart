// Z-Forge application configuration (stored in insecure/shared preferences).
// Includes player preferences and platform-specific storage paths.
// See docs/Player Preferences.md and docs/User Experience.md — ZForgeConfig section.

/// Player preferences used to tune generated experiences.
/// All scales are 1–10 in the order specified; default is 5.
/// See docs/Player Preferences.md for full specification.
class PlayerPreferences {
  /// 1 = strong preference for character development; 10 = strong preference for plot.
  final int characterToPlot;

  /// 1 = prefers narrative description; 10 = prefers dialogue-driven storytelling.
  final int narrativeToDialog;

  /// 1 = minimal/no puzzles; 10 = challenging puzzles.
  final int puzzleComplexity;

  /// 1 = somber/intense tone; 10 = comedic/uplifting tone.
  final int levity;

  /// Free-text field for any additional general preferences.
  final String? generalPreferences;

  /// 1 = mood/atmosphere is paramount; 10 = logical consistency is paramount.
  final int logicalVsMood;

  const PlayerPreferences({
    this.characterToPlot = 5,
    this.narrativeToDialog = 5,
    this.puzzleComplexity = 5,
    this.levity = 5,
    this.generalPreferences,
    this.logicalVsMood = 5,
  });

  factory PlayerPreferences.fromJson(Map<String, dynamic> json) =>
      PlayerPreferences(
        characterToPlot: (json['character_to_plot'] as num?)?.toInt() ?? 5,
        narrativeToDialog: (json['narrative_to_dialog'] as num?)?.toInt() ?? 5,
        puzzleComplexity: (json['puzzle_complexity'] as num?)?.toInt() ?? 5,
        levity: (json['levity'] as num?)?.toInt() ?? 5,
        generalPreferences: json['general_preferences'] as String?,
        logicalVsMood: (json['logical_vs_mood'] as num?)?.toInt() ?? 5,
      );

  Map<String, dynamic> toJson() => {
        'character_to_plot': characterToPlot,
        'narrative_to_dialog': narrativeToDialog,
        'puzzle_complexity': puzzleComplexity,
        'levity': levity,
        if (generalPreferences != null)
          'general_preferences': generalPreferences,
        'logical_vs_mood': logicalVsMood,
      };

  PlayerPreferences copyWith({
    int? characterToPlot,
    int? narrativeToDialog,
    int? puzzleComplexity,
    int? levity,
    String? generalPreferences,
    int? logicalVsMood,
  }) =>
      PlayerPreferences(
        characterToPlot: characterToPlot ?? this.characterToPlot,
        narrativeToDialog: narrativeToDialog ?? this.narrativeToDialog,
        puzzleComplexity: puzzleComplexity ?? this.puzzleComplexity,
        levity: levity ?? this.levity,
        generalPreferences: generalPreferences ?? this.generalPreferences,
        logicalVsMood: logicalVsMood ?? this.logicalVsMood,
      );
}

class ZForgeConfig {
  final PlayerPreferences preferences;

  /// Mac/PC only: path to directory where .zworld files are stored.
  /// Defaults to ~/zforge/worlds/. Null on mobile/web.
  final String? zWorldFolderPath;

  /// Mac/PC only: path to directory where compiled experience files are stored.
  /// Defaults to ~/zforge/experiences/. Null on mobile/web.
  final String? experienceFolderPath;

  const ZForgeConfig({
    this.preferences = const PlayerPreferences(),
    this.zWorldFolderPath,
    this.experienceFolderPath,
  });

  factory ZForgeConfig.fromJson(Map<String, dynamic> json) => ZForgeConfig(
        preferences: json['preferences'] != null
            ? PlayerPreferences.fromJson(
                json['preferences'] as Map<String, dynamic>)
            : const PlayerPreferences(),
        zWorldFolderPath: json['zworld_folder_path'] as String?,
        experienceFolderPath: json['experience_folder_path'] as String?,
      );

  Map<String, dynamic> toJson() => {
        'preferences': preferences.toJson(),
        if (zWorldFolderPath != null) 'zworld_folder_path': zWorldFolderPath,
        if (experienceFolderPath != null)
          'experience_folder_path': experienceFolderPath,
      };

  ZForgeConfig copyWith({
    PlayerPreferences? preferences,
    String? zWorldFolderPath,
    String? experienceFolderPath,
  }) =>
      ZForgeConfig(
        preferences: preferences ?? this.preferences,
        zWorldFolderPath: zWorldFolderPath ?? this.zWorldFolderPath,
        experienceFolderPath: experienceFolderPath ?? this.experienceFolderPath,
      );
}
