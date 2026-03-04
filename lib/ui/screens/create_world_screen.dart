import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:file_picker/file_picker.dart';
import '../../app_state.dart';
import '../../processes/create_world_process.dart';

/// Screen for creating a new ZWorld from a plain-text description.
///
/// The user may type or paste text directly, or load a file (Word/PDF/text).
/// Triggers [CreateWorldProcess] and shows live status updates.
///
/// See docs/World Generation.md for the full workflow.
/// Implemented in: lib/ui/screens/create_world_screen.dart
class CreateWorldScreen extends StatefulWidget {
  const CreateWorldScreen({super.key});

  @override
  State<CreateWorldScreen> createState() => _CreateWorldScreenState();
}

class _CreateWorldScreenState extends State<CreateWorldScreen> {
  final _controller = TextEditingController();
  CreateWorldProcess? _process;

  @override
  void dispose() {
    _controller.dispose();
    _process?.dispose();
    super.dispose();
  }

  Future<void> _pickFile() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['txt', 'md', 'pdf', 'docx', 'doc'],
      withData: true,
    );
    if (result != null && result.files.single.bytes != null) {
      final file = result.files.single;
      final name = file.name.toLowerCase();
      if (name.endsWith('.txt') || name.endsWith('.md')) {
        _controller.text = String.fromCharCodes(file.bytes!);
      } else {
        _showSnack(
            'Only .txt and .md files can be read directly. '
            'Please paste your world description as text.');
      }
    }
  }




  void _showSnack(String msg) {
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<void> _submit() async {
    final text = _controller.text.trim();
    if (text.isEmpty) {
      _showSnack('Please enter a world description.');
      return;
    }

    final state = context.read<AppState>();
    _process?.dispose();
    final process = CreateWorldProcess(
      connector: state.connector,
      config: state.config,
    );

    setState(() => _process = process);
    process.addListener(() => setState(() {}));
    await process.run(text);

    if (process.status == CreateWorldStatus.success && mounted) {
      Navigator.of(context).pop();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('World "${process.world?.name}" created!'),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final process = _process;
    final running = process?.isRunning ?? false;

    return Scaffold(
      appBar: AppBar(title: const Text('Create World')),
      body: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // File picker row
            Row(
              children: [
                Expanded(
                  child: Text(
                    'Describe your world (or load a file):',
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                ),
                TextButton.icon(
                  icon: const Icon(Icons.upload_file),
                  label: const Text('Load file'),
                  onPressed: running ? null : _pickFile,
                ),
              ],
            ),
            const SizedBox(height: 8),
            // Text input
            Expanded(
              child: TextField(
                controller: _controller,
                enabled: !running,
                maxLines: null,
                expands: true,
                textAlignVertical: TextAlignVertical.top,
                decoration: const InputDecoration(
                  border: OutlineInputBorder(),
                  hintText:
                      'e.g. "Discworld is a flat world balanced on four elephants '
                      'standing on a giant turtle. Major cities include Ankh-Morpork...',
                ),
              ),
            ),
            const SizedBox(height: 12),
            // Status display
            if (process != null) _StatusPanel(process: process),
            const SizedBox(height: 12),
            // Submit button
            FilledButton(
              onPressed: running ? null : _submit,
              child: running
                  ? const Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        SizedBox(
                          height: 18,
                          width: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                        SizedBox(width: 12),
                        Text('Generating…'),
                      ],
                    )
                  : const Text('Create World'),
            ),
          ],
        ),
      ),
    );
  }
}

class _StatusPanel extends StatelessWidget {
  final CreateWorldProcess process;

  const _StatusPanel({required this.process});

  @override
  Widget build(BuildContext context) {
    final color = switch (process.status) {
      CreateWorldStatus.success => Colors.green,
      CreateWorldStatus.failed ||
      CreateWorldStatus.inputRejected =>
        Theme.of(context).colorScheme.error,
      _ => Theme.of(context).colorScheme.primary,
    };

    final message = switch (process.status) {
      CreateWorldStatus.validatingInput =>
        'Validating description (attempt ${process.validationAttempts}/${CreateWorldProcess.maxValidationAttempts})…',
      CreateWorldStatus.generatingWorld => 'Generating world…',
      CreateWorldStatus.saving => 'Saving world…',
      CreateWorldStatus.success =>
        'World "${process.world?.name}" created successfully!',
      CreateWorldStatus.inputRejected =>
        process.errorMessage ??
            'Description rejected. Please revise and try again.',
      CreateWorldStatus.failed =>
        process.errorMessage ?? 'An error occurred.',
      CreateWorldStatus.idle => '',
    };

    if (message.isEmpty) return const SizedBox.shrink();

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        border: Border.all(color: color),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(message, style: TextStyle(color: color)),
    );
  }
}
