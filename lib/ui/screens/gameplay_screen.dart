import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../app_state.dart';
import '../../services/managers/experience_manager.dart';
import '../../services/if_engine/if_engine_connector.dart';

/// Typewriter-style gameplay screen for playing an interactive fiction
/// experience via the [IfEngineConnector].
///
/// - Scrolling output area with game text left-justified and player input
///   right-justified (chat-style, no bubbles).
/// - Choice buttons rendered below the output.
/// - Input field at the bottom for typing choice numbers.
/// - Menu supports Save/Restore.
///
/// See docs/User Experience.md — Gameplay Interface.
/// Implemented in: lib/ui/screens/gameplay_screen.dart
class GameplayScreen extends StatefulWidget {
  final Experience experience;
  final bool restore;

  const GameplayScreen({
    super.key,
    required this.experience,
    this.restore = false,
  });

  @override
  State<GameplayScreen> createState() => _GameplayScreenState();
}

class _GameplayScreenState extends State<GameplayScreen> {
  final ScrollController _scrollCtrl = ScrollController();
  final TextEditingController _inputCtrl = TextEditingController();
  final List<_OutputEntry> _output = [];
  List<String> _choices = [];
  bool _isComplete = false;
  bool _loading = true;
  String? _error;

  late AppState _state;

  @override
  void initState() {
    super.initState();
    _state = context.read<AppState>();
    _start();
  }

  @override
  void dispose() {
    _scrollCtrl.dispose();
    _inputCtrl.dispose();
    super.dispose();
  }

  Future<void> _start() async {
    try {
      final data =
          await ExperienceManager.instance.loadCompiledData(widget.experience);
      debugPrint('[GameplayScreen] Loaded compiled data: ${data.length} bytes');

      if (widget.restore) {
        final saved =
            await ExperienceManager.instance.loadProgress(widget.experience);
        if (saved != null) {
          final text = await _state.ifEngine.restoreState(saved);
          _addGameText(text);
          final choices = await _state.ifEngine.getCurrentChoices();
          setState(() {
            _choices = choices;
            _loading = false;
          });
          _scrollToBottom();
          return;
        }
      }

      debugPrint('[GameplayScreen] Starting experience...');
      final openingText = await _state.ifEngine.startExperience(data);
      debugPrint('[GameplayScreen] Opening text: "$openingText"');
      _addGameText(openingText);
      final choices = await _state.ifEngine.getCurrentChoices();
      debugPrint('[GameplayScreen] Choices: $choices');
      setState(() {
        _choices = choices;
        _loading = false;
      });
      _scrollToBottom();
    } catch (e, stack) {
      debugPrint('[GameplayScreen] Error: $e');
      debugPrint('[GameplayScreen] Stack: $stack');
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  void _addGameText(String text) {
    if (text.isNotEmpty) {
      _output.add(_OutputEntry(text: text, isPlayer: false));
    }
  }

  void _addPlayerText(String text) {
    _output.add(_OutputEntry(text: text, isPlayer: true));
  }

  Future<void> _selectChoice(int index) async {
    if (index < 0 || index >= _choices.length) return;

    _addPlayerText(_choices[index]);
    setState(() {
      _choices = [];
      _inputCtrl.clear();
    });

    try {
      final result = await _state.ifEngine.takeAction(index.toString());
      _addGameText(result.text);
      setState(() {
        _choices = result.choices ?? [];
        _isComplete = result.isComplete;
      });
      _scrollToBottom();
    } catch (e) {
      setState(() {
        _error = e.toString();
      });
    }
  }

  void _onSubmit(String value) {
    final idx = int.tryParse(value.trim());
    if (idx != null && idx >= 1 && idx <= _choices.length) {
      _selectChoice(idx - 1); // displayed 1-indexed, internal 0-indexed
    }
  }

  Future<void> _saveProgress() async {
    try {
      final bytes = await _state.ifEngine.saveState();
      await ExperienceManager.instance
          .saveProgress(widget.experience, bytes);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Progress saved')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Save failed: $e')),
        );
      }
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollCtrl.hasClients) {
        _scrollCtrl.animateTo(
          _scrollCtrl.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.experience.name),
        actions: [
          if (!_isComplete)
            IconButton(
              icon: const Icon(Icons.save),
              tooltip: 'Save Progress',
              onPressed: _saveProgress,
            ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(
                      'Error: $_error',
                      style: TextStyle(
                          color: Theme.of(context).colorScheme.error),
                    ),
                  ),
                )
              : Column(
                  children: [
                    // Scrolling output area
                    Expanded(
                      child: ListView.builder(
                        controller: _scrollCtrl,
                        padding: const EdgeInsets.all(16),
                        itemCount: _output.length +
                            (_isComplete ? 1 : 0) +
                            (_choices.isNotEmpty ? 1 : 0),
                        itemBuilder: (_, i) {
                          if (i < _output.length) {
                            final entry = _output[i];
                            return Align(
                              alignment: entry.isPlayer
                                  ? Alignment.centerRight
                                  : Alignment.centerLeft,
                              child: Container(
                                margin:
                                    const EdgeInsets.symmetric(vertical: 4),
                                constraints: BoxConstraints(
                                  maxWidth:
                                      MediaQuery.of(context).size.width *
                                          0.85,
                                ),
                                child: Text(
                                  entry.text,
                                  style: const TextStyle(
                                    fontFamily: 'Courier',
                                    fontSize: 14,
                                    height: 1.5,
                                  ),
                                ),
                              ),
                            );
                          }
                          // Choice buttons
                          if (_choices.isNotEmpty &&
                              i == _output.length) {
                            return Padding(
                              padding:
                                  const EdgeInsets.symmetric(vertical: 8),
                              child: Wrap(
                                spacing: 8,
                                runSpacing: 8,
                                children: List.generate(
                                  _choices.length,
                                  (ci) => OutlinedButton(
                                    onPressed: () => _selectChoice(ci),
                                    child: Text(
                                        '${ci + 1}. ${_choices[ci]}'),
                                  ),
                                ),
                              ),
                            );
                          }
                          // Completion message
                          if (_isComplete) {
                            return Padding(
                              padding:
                                  const EdgeInsets.symmetric(vertical: 16),
                              child: Column(
                                children: [
                                  const Text(
                                    '— Experience Complete —',
                                    style: TextStyle(
                                      fontFamily: 'Courier',
                                      fontSize: 16,
                                      fontWeight: FontWeight.bold,
                                    ),
                                    textAlign: TextAlign.center,
                                  ),
                                  const SizedBox(height: 12),
                                  FilledButton(
                                    onPressed: () =>
                                        Navigator.of(context).pop(),
                                    child:
                                        const Text('Return to Home'),
                                  ),
                                ],
                              ),
                            );
                          }
                          return const SizedBox.shrink();
                        },
                      ),
                    ),
                    // Input area
                    if (!_isComplete)
                      Container(
                        padding: const EdgeInsets.all(8),
                        decoration: BoxDecoration(
                          border: Border(
                            top: BorderSide(
                              color: Theme.of(context).dividerColor,
                            ),
                          ),
                        ),
                        child: Row(
                          children: [
                            Expanded(
                              child: TextField(
                                controller: _inputCtrl,
                                onSubmitted: _onSubmit,
                                decoration: InputDecoration(
                                  hintText: _choices.isNotEmpty
                                      ? 'Enter choice number or tap above'
                                      : 'Waiting…',
                                  border: const OutlineInputBorder(),
                                  contentPadding:
                                      const EdgeInsets.symmetric(
                                          horizontal: 12, vertical: 8),
                                ),
                                enabled: _choices.isNotEmpty,
                              ),
                            ),
                            const SizedBox(width: 8),
                            IconButton(
                              icon: const Icon(Icons.subdirectory_arrow_left),
                              onPressed: _choices.isNotEmpty
                                  ? () => _onSubmit(_inputCtrl.text)
                                  : null,
                            ),
                          ],
                        ),
                      ),
                  ],
                ),
    );
  }
}

class _OutputEntry {
  final String text;
  final bool isPlayer;

  const _OutputEntry({required this.text, required this.isPlayer});
}
