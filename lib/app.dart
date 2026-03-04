import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'app_state.dart';
import 'ui/app_router.dart';

/// Root [MaterialApp] for Z-Forge.
/// Provides [AppState] to the entire widget tree.
///
/// Implemented in: lib/app.dart
class ZForgeApp extends StatelessWidget {
  const ZForgeApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (_) => AppState()..initialize(),
      child: MaterialApp(
        title: 'Z-Forge',
        theme: ThemeData(
          colorScheme:
              ColorScheme.fromSeed(seedColor: const Color(0xFF2D4A22)),
          textTheme: GoogleFonts.sourceCodeProTextTheme(),
          useMaterial3: true,
        ),
        home: const AppRouter(),
        debugShowCheckedModeBanner: false,
      ),
    );
  }
}
