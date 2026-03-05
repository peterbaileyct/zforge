import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../app_state.dart';
import '../../models/zworld.dart';
import '../../processes/experience_generation_process.dart';
import '../../services/managers/experience_manager.dart';
import 'gameplay_screen.dart';

/// Screen for generating an interactive fiction experience from a [ZWorld].
///
/// Shows the selected world name, an optional player prompt input, and a
/// Generate button. During generation, displays the process's [statusMessage].
/// On success, offers to play the experience; on failure, shows the
/// [failureReason].
///
/// See docs/User Experience.md — Experience Generation UI.
/// Implemented in: lib/ui/screens/generate_experience_screen.dart
class GenerateExperienceScreen extends StatefulWidget {
  final ZWorld world;

  const GenerateExperienceScreen({super.key, required this.world});

  @override
  State<GenerateExperienceScreen> createState() =>
      _GenerateExperienceScreenState();
}

class _GenerateExperienceScreenState extends State<GenerateExperienceScreen> {
  final _promptController = TextEditingController();
  ExperienceGenerationProcess? _process;
  bool _generating = false;

  @override
  void dispose() {
    _promptController.dispose();
    _process?.dispose();
    super.dispose();
  }

  Future<void> _generate() async {
    final state = context.read<AppState>();
    setState(() => _generating = true);

    final process = ExperienceGenerationProcess(
      connector: state.connector,
      ifEngine: state.ifEngine,
    );
    _process = process;
    process.addListener(() {
      if (mounted) setState(() {});
    });

    await process.run(
      widget.world,
      state.config.preferences,
      _promptController.text.trim().isEmpty
          ? null
          : _promptController.text.trim(),
    );

    if (!mounted) return;
    setState(() => _generating = false);

    if (process.status == ExperienceGenerationStatus.complete &&
        process.compiledOutput != null) {
      final experience = await ExperienceManager.instance.save(
        widget.world,
        'experience-${DateTime.now().millisecondsSinceEpoch}',
        process.compiledOutput!,
        state.ifEngine.getFileExtension(),
        state.config,
      );

      if (!mounted) return;
      final play = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Experience Created'),
          content: const Text('Your experience is ready. Play now?'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Later'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Play Now'),
            ),
          ],
        ),
      );

      if (play == true && mounted) {
        Navigator.of(context).pushReplacement(MaterialPageRoute(
          builder: (_) => ChangeNotifierProvider.value(
            value: state,
            child: GameplayScreen(experience: experience),
          ),
        ));
      } else if (mounted) {
        Navigator.of(context).pop();
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final statusMsg = _process?.statusMessage ?? '';
    final failed = _process?.status == ExperienceGenerationStatus.failed;

    return Scaffold(
      appBar: AppBar(title: const Text('Generate Experience')),
      body: Padding(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'World: ${widget.world.name}',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _promptController,
              enabled: !_generating,
              maxLines: 3,
              decoration: const InputDecoration(
                labelText: 'Player Prompt (optional)',
                hintText:
                    'Describe the kind of experience you want, e.g. '
                    '"A mystery set in the bank" or "Something humorous"',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 24),
            if (_generating || _process != null) ...[
              LinearProgressIndicator(
                value: _generating ? null : (failed ? 1.0 : 1.0),
                color: failed
                    ? Theme.of(context).colorScheme.error
                    : null,
              ),
              const SizedBox(height: 12),
              Text(
                statusMsg,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: failed
                          ? Theme.of(context).colorScheme.error
                          : null,
                      fontWeight: FontWeight.bold,
                    ),
              ),
              if (_process?.currentRationale != null) ...[
                const SizedBox(height: 8),
                Text(
                  _process!.currentRationale!,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        fontStyle: FontStyle.italic,
                      ),
                ),
              ],
              const SizedBox(height: 16),
              if (_process != null && _process!.actionLog.isNotEmpty) ...[
                Text(
                  'Action Log',
                  style: Theme.of(context).textTheme.titleSmall,
                ),
                const SizedBox(height: 8),
                Expanded(
                  child: Container(
                    decoration: BoxDecoration(
                      border: Border.all(
                        color: Theme.of(context).colorScheme.outline,
                      ),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    padding: const EdgeInsets.all(12),
                    child: ListView.separated(
                      itemCount: _process!.actionLog.length,
                      separatorBuilder: (_, __) => const Divider(),
                      itemBuilder: (_, index) {
                        final entry = _process!.actionLog[index];
                        return Text(
                          entry.toString(),
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                fontFamily: 'monospace',
                              ),
                        );
                      },
                    ),
                  ),
                ),
                const SizedBox(height: 12),
              ],
              if (failed)
                Text(
                  _process?.failureReason ?? 'Unknown error.',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.error,
                      ),
                ),
            ],
            const Spacer(),
            FilledButton(
              onPressed: _generating ? null : _generate,
              child: _generating
                  ? const SizedBox(
                      height: 18,
                      width: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('Generate'),
            ),
          ],
        ),
      ),
    );
  }
}
