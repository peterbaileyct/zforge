import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../app_state.dart';
import '../../models/zworld.dart';
import '../../services/managers/zworld_manager.dart';
import '../../services/managers/experience_manager.dart';
import '../widgets/world_list_tile.dart';
import 'create_world_screen.dart';
import 'generate_experience_screen.dart';
import 'gameplay_screen.dart';
import 'preferences_screen.dart';
import 'llm_config_screen.dart';

/// The main screen of Z-Forge.
///
/// Displays the list of available ZWorlds and context-sensitive action buttons.
/// On macOS/Windows the main menu bar is used; on mobile/web a hamburger
/// menu appears.
///
/// See docs/User Experience.md — Main UI section.
/// Implemented in: lib/ui/screens/home_screen.dart
class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return _HomeScreenContent();
  }
}

class _HomeScreenContent extends StatefulWidget {
  @override
  State<_HomeScreenContent> createState() => _HomeScreenContentState();
}

class _HomeScreenContentState extends State<_HomeScreenContent>
    with WidgetsBindingObserver {
  bool _hasExperiences = false;
  bool _hasSaves = false;
  int? _selectedWorldIndex;
  bool _capabilitiesLoaded = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _loadCapabilities();
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // Load capabilities once AppState is initialized
    final state = context.read<AppState>();
    if (state.initialized && !_capabilitiesLoaded) {
      _capabilitiesLoaded = true;
      _loadCapabilities();
    }
  }

  Future<void> _loadCapabilities() async {
    final state = context.read<AppState>();
    final exp = await state.hasExperiences();
    final saves = await state.hasSaves();
    if (mounted) {
      setState(() {
        _hasExperiences = exp;
        _hasSaves = saves;
      });
    }
  }

  bool get _isDesktop =>
      !kIsWeb &&
      (defaultTargetPlatform == TargetPlatform.macOS ||
          defaultTargetPlatform == TargetPlatform.windows ||
          defaultTargetPlatform == TargetPlatform.linux);

  ZWorld? get _selectedWorld {
    final worlds = context.read<AppState>().worlds;
    if (_selectedWorldIndex != null &&
        _selectedWorldIndex! < worlds.length) {
      return worlds[_selectedWorldIndex!];
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final worlds = state.worlds;
    final hasWorlds = worlds.isNotEmpty;

    final menuItems = _buildMenuItems(context, state, hasWorlds);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Z-Forge'),
        actions: _isDesktop
            ? menuItems
                .map((item) => TextButton(
                      onPressed: item.enabled ? item.onPressed : null,
                      child: Text(item.label),
                    ))
                .toList()
            : [
                PopupMenuButton<_MenuItem>(
                  icon: const Icon(Icons.menu),
                  itemBuilder: (_) => menuItems
                      .map((item) => PopupMenuItem(
                            value: item,
                            enabled: item.enabled,
                            child: Text(item.label),
                          ))
                      .toList(),
                  onSelected: (item) => item.onPressed?.call(),
                ),
              ],
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Contextual action buttons
          Padding(
            padding: const EdgeInsets.all(16.0),
            child: Wrap(
              spacing: 12,
              runSpacing: 12,
              children: [
                FilledButton.icon(
                  icon: const Icon(Icons.add),
                  label: const Text('Create World'),
                  onPressed: () => _openCreateWorld(context),
                ),
                FilledButton.icon(
                  icon: const Icon(Icons.auto_stories),
                  label: const Text('Create Experience'),
                  onPressed: hasWorlds && _selectedWorld != null
                      ? () => _openGenerateExperience(context)
                      : null,
                ),
                if (_hasExperiences)
                  FilledButton.icon(
                    icon: const Icon(Icons.play_arrow),
                    label: const Text('Start Experience'),
                    onPressed: () => _openStartExperience(context),
                  ),
                if (_hasSaves)
                  FilledButton.icon(
                    icon: const Icon(Icons.restore),
                    label: const Text('Resume Experience'),
                    onPressed: () => _openResumeExperience(context),
                  ),
              ],
            ),
          ),
          const Divider(),
          // World list
          Expanded(
            child: worlds.isEmpty
                ? const Center(
                    child: Text(
                      'No worlds yet.\nCreate a world to get started.',
                      textAlign: TextAlign.center,
                    ),
                  )
                : ListView.builder(
                    itemCount: worlds.length,
                    itemBuilder: (_, i) => WorldListTile(
                      world: worlds[i],
                      selected: _selectedWorldIndex == i,
                      onTap: () => setState(() => _selectedWorldIndex = i),
                      onDelete: () => ZWorldManager.instance
                          .delete(worlds[i].id, state.config),
                    ),
                  ),
          ),
        ],
      ),
    );
  }

  void _openCreateWorld(BuildContext context) {
    final state = context.read<AppState>();
    Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => ChangeNotifierProvider.value(
        value: state,
        child: const CreateWorldScreen(),
      ),
    )).then((_) => _loadCapabilities());
  }

  void _openGenerateExperience(BuildContext context) {
    final world = _selectedWorld;
    if (world == null) return;
    final state = context.read<AppState>();
    Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => ChangeNotifierProvider.value(
        value: state,
        child: GenerateExperienceScreen(world: world),
      ),
    )).then((_) => _loadCapabilities());
  }

  Future<void> _openStartExperience(BuildContext context) async {
    final state = context.read<AppState>();
    final experiences =
        await ExperienceManager.instance.listAll(state.config);
    if (!mounted || experiences.isEmpty) return;

    final selected = await showDialog<Experience>(
      context: context,
      builder: (ctx) => SimpleDialog(
        title: const Text('Select Experience'),
        children: experiences
            .map((e) => SimpleDialogOption(
                  onPressed: () => Navigator.pop(ctx, e),
                  child: Text('${e.name} (${e.zworldId})'),
                ))
            .toList(),
      ),
    );
    if (selected != null && mounted) {
      Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => ChangeNotifierProvider.value(
          value: state,
          child: GameplayScreen(experience: selected),
        ),
      ));
      _loadCapabilities();
    }
  }

  Future<void> _openResumeExperience(BuildContext context) async {
    final state = context.read<AppState>();
    final experiences =
        await ExperienceManager.instance.listAll(state.config);
    final withSaves = <Experience>[];
    for (final e in experiences) {
      final progress =
          await ExperienceManager.instance.loadProgress(e);
      if (progress != null) withSaves.add(e);
    }
    if (!mounted || withSaves.isEmpty) return;

    final selected = await showDialog<Experience>(
      context: context,
      builder: (ctx) => SimpleDialog(
        title: const Text('Resume Experience'),
        children: withSaves
            .map((e) => SimpleDialogOption(
                  onPressed: () => Navigator.pop(ctx, e),
                  child: Text('${e.name} (${e.zworldId})'),
                ))
            .toList(),
      ),
    );
    if (selected != null && mounted) {
      Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => ChangeNotifierProvider.value(
          value: state,
          child: GameplayScreen(experience: selected, restore: true),
        ),
      ));
    }
  }

  List<_MenuItem> _buildMenuItems(
      BuildContext context, AppState state, bool hasWorlds) {
    return [
      _MenuItem(
        label: 'Create World',
        enabled: true,
        onPressed: () => _openCreateWorld(context),
      ),
      _MenuItem(
        label: 'Create Experience',
        enabled: hasWorlds && _selectedWorld != null,
        onPressed: hasWorlds && _selectedWorld != null
            ? () => _openGenerateExperience(context)
            : null,
      ),
      _MenuItem(
        label: 'Preferences',
        enabled: true,
        onPressed: () => Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => ChangeNotifierProvider.value(
              value: state,
              child: const PreferencesScreen(),
            ),
          ),
        ),
      ),
      _MenuItem(
        label: 'LLM Settings',
        enabled: true,
        onPressed: () => Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => ChangeNotifierProvider.value(
              value: state,
              child: const LlmConfigScreen(),
            ),
          ),
        ),
      ),
    ];
  }
}

class _MenuItem {
  final String label;
  final bool enabled;
  final VoidCallback? onPressed;

  const _MenuItem({
    required this.label,
    this.enabled = true,
    this.onPressed,
  });
}
