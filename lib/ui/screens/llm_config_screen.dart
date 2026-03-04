import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../app_state.dart';
import 'home_screen.dart';

/// Prompts the user to enter LLM credentials.
/// Pre-populates any existing values from secure storage.
/// On successful validation the credentials are stored and the user proceeds
/// to [HomeScreen].
///
/// See docs/User Experience.md — LLM Configuration section.
/// Implemented in: lib/ui/screens/llm_config_screen.dart
class LlmConfigScreen extends StatefulWidget {
  const LlmConfigScreen({super.key});

  @override
  State<LlmConfigScreen> createState() => _LlmConfigScreenState();
}

class _LlmConfigScreenState extends State<LlmConfigScreen> {
  final Map<String, TextEditingController> _controllers = {};
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    final state = context.read<AppState>();
    final connector = state.connector;
    final existing =
        state.secureConfig.connectors[connector.connectorName]?.values ?? {};
    for (final key in connector.configKeys) {
      _controllers[key] =
          TextEditingController(text: existing[key] ?? '');
    }
  }

  @override
  void dispose() {
    for (final c in _controllers.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _submit() async {
    final state = context.read<AppState>();
    setState(() {
      _saving = true;
      _error = null;
    });

    final values = {
      for (final e in _controllers.entries) e.key: e.value.text.trim()
    };
    final error = await state.saveLlmConfig(values);

    if (!mounted) return;
    if (error != null) {
      setState(() {
        _saving = false;
        _error = error;
      });
    } else {
      setState(() => _saving = false);
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => const HomeScreen()),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final connectorName = state.connector.connectorName;
    final keys = state.connector.configKeys;

    return Scaffold(
      appBar: AppBar(title: const Text('Z-Forge — LLM Configuration')),
      body: Padding(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '$connectorName configuration has not been provided.',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 24),
            for (final key in keys) ...[
              Text(
                key
                    .replaceAll('_', ' ')
                    .split(' ')
                    .map((w) =>
                        w.isNotEmpty
                            ? w[0].toUpperCase() + w.substring(1)
                            : w)
                    .join(' '),
                style: Theme.of(context).textTheme.labelLarge,
              ),
              const SizedBox(height: 8),
              TextField(
                controller: _controllers[key],
                obscureText: key.toLowerCase().contains('key') ||
                    key.toLowerCase().contains('secret'),
                decoration: InputDecoration(
                  border: const OutlineInputBorder(),
                  hintText: 'Enter $key',
                ),
              ),
              const SizedBox(height: 16),
            ],
            if (_error != null) ...[
              Text(
                _error!,
                style: TextStyle(
                    color: Theme.of(context).colorScheme.error),
              ),
              const SizedBox(height: 16),
            ],
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: _saving ? null : _submit,
                child: _saving
                    ? const SizedBox(
                        height: 20,
                        width: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Text('Save & Validate'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
