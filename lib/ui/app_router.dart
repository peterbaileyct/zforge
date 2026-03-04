import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../app_state.dart';
import 'screens/llm_config_screen.dart';
import 'screens/home_screen.dart';

/// Root widget. Decides whether to show [LlmConfigScreen] (if credentials
/// are missing) or [HomeScreen] (normal entry point).
///
/// Implemented in: lib/ui/app_router.dart
class AppRouter extends StatelessWidget {
  const AppRouter({super.key});

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();

    if (!state.initialized) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }

    if (!state.llmConfigured) {
      return const LlmConfigScreen();
    }

    return const HomeScreen();
  }
}
