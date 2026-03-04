import 'package:flutter_test/flutter_test.dart';
import 'package:zforge/app.dart';

void main() {
  testWidgets('Z-Forge app smoke test', (WidgetTester tester) async {
    await tester.pumpWidget(const ZForgeApp());
    expect(find.byType(ZForgeApp), findsOneWidget);
  });
}
