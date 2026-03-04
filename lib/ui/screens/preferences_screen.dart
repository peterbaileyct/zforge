import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../app_state.dart';
import '../../models/zforge_config.dart';
import '../../services/managers/zworld_manager.dart';

/// Screen for viewing and editing player preferences.
///
/// Preferences (all 1–10 scales):
/// - Character to Plot
/// - Narrative to Dialog
/// - Puzzle Complexity
/// - Levity
/// - Logical vs. Mood
/// - General Preferences (free text)
///
/// See docs/Player Preferences.md.
/// Implemented in: lib/ui/screens/preferences_screen.dart
class PreferencesScreen extends StatefulWidget {
  const PreferencesScreen({super.key});

  @override
  State<PreferencesScreen> createState() => _PreferencesScreenState();
}

class _PreferencesScreenState extends State<PreferencesScreen> {
  late double _characterToPlot;
  late double _narrativeToDialog;
  late double _puzzleComplexity;
  late double _levity;
  late double _logicalVsMood;
  late TextEditingController _generalPrefsController;
  bool _saving = false;
  String? _zWorldPath;

  @override
  void initState() {
    super.initState();
    final prefs = context.read<AppState>().config.preferences;
    _characterToPlot = prefs.characterToPlot.toDouble();
    _narrativeToDialog = prefs.narrativeToDialog.toDouble();
    _puzzleComplexity = prefs.puzzleComplexity.toDouble();
    _levity = prefs.levity.toDouble();
    _logicalVsMood = prefs.logicalVsMood.toDouble();
    _generalPrefsController =
        TextEditingController(text: prefs.generalPreferences ?? '');
    _resolveZWorldPath();
  }

  Future<void> _resolveZWorldPath() async {
    final config = context.read<AppState>().config;
    try {
      final dir = await ZWorldManager.instance.resolveStorageDir(config);
      if (mounted) setState(() => _zWorldPath = dir.path);
    } catch (_) {
      if (mounted) setState(() => _zWorldPath = 'Unavailable');
    }
  }

  @override
  void dispose() {
    _generalPrefsController.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    final state = context.read<AppState>();
    final updated = state.config.copyWith(
      preferences: PlayerPreferences(
        characterToPlot: _characterToPlot.round(),
        narrativeToDialog: _narrativeToDialog.round(),
        puzzleComplexity: _puzzleComplexity.round(),
        levity: _levity.round(),
        logicalVsMood: _logicalVsMood.round(),
        generalPreferences: _generalPrefsController.text.trim().isEmpty
            ? null
            : _generalPrefsController.text.trim(),
      ),
    );
    await state.saveConfig(updated);
    if (mounted) {
      setState(() => _saving = false);
      Navigator.of(context).pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Preferences')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _SectionLabel(
              'Character ↔ Plot (${_characterToPlot.round()})',
              '1 = character focus · 10 = plot focus',
            ),
            Slider(
              value: _characterToPlot,
              min: 1,
              max: 10,
              divisions: 9,
              label: _characterToPlot.round().toString(),
              onChanged: (v) => setState(() => _characterToPlot = v),
            ),
            const SizedBox(height: 12),
            _SectionLabel(
              'Narrative ↔ Dialog (${_narrativeToDialog.round()})',
              '1 = rich narrative · 10 = dialogue-driven',
            ),
            Slider(
              value: _narrativeToDialog,
              min: 1,
              max: 10,
              divisions: 9,
              label: _narrativeToDialog.round().toString(),
              onChanged: (v) => setState(() => _narrativeToDialog = v),
            ),
            const SizedBox(height: 12),
            _SectionLabel(
              'Puzzle Complexity (${_puzzleComplexity.round()})',
              '1 = minimal puzzles · 10 = challenging puzzles',
            ),
            Slider(
              value: _puzzleComplexity,
              min: 1,
              max: 10,
              divisions: 9,
              label: _puzzleComplexity.round().toString(),
              onChanged: (v) => setState(() => _puzzleComplexity = v),
            ),
            const SizedBox(height: 12),
            _SectionLabel(
              'Levity (${_levity.round()})',
              '1 = somber/intense · 10 = comedic/uplifting',
            ),
            Slider(
              value: _levity,
              min: 1,
              max: 10,
              divisions: 9,
              label: _levity.round().toString(),
              onChanged: (v) => setState(() => _levity = v),
            ),
            const SizedBox(height: 12),
            _SectionLabel(
              'Logical vs. Mood (${_logicalVsMood.round()})',
              '1 = mood/atmosphere priority · 10 = logical consistency priority',
            ),
            Slider(
              value: _logicalVsMood,
              min: 1,
              max: 10,
              divisions: 9,
              label: _logicalVsMood.round().toString(),
              onChanged: (v) => setState(() => _logicalVsMood = v),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _generalPrefsController,
              maxLines: 3,
              decoration: const InputDecoration(
                labelText: 'General preferences (optional)',
                hintText:
                    'Describe any additional preferences for your experiences',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 24),
            _SectionLabel(
                'ZWorld file storage', 'Where .zworld files are written'),
            const SizedBox(height: 4),
            Text(
              _zWorldPath ?? 'Resolving…',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    fontFamily: 'monospace',
                    color: _zWorldPath == null ? Colors.grey : null,
                  ),
            ),
            const SizedBox(height: 32),
            FilledButton(
              onPressed: _saving ? null : _save,
              child: _saving
                  ? const SizedBox(
                      height: 18,
                      width: 18,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : const Text('Save Preferences'),
            ),
          ],
        ),
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  final String title;
  final String subtitle;

  const _SectionLabel(this.title, this.subtitle);

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: Theme.of(context).textTheme.titleSmall),
        Text(subtitle,
            style: Theme.of(context)
                .textTheme
                .bodySmall
                ?.copyWith(color: Colors.grey)),
      ],
    );
  }
}
