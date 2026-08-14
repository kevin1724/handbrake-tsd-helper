import 'package:bytesqueeze/main.dart';
import 'package:bytesqueeze/src/app_controller.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('demo opens the ByteSqueeze dashboard', (tester) async {
    final controller = AppController()..enterDemo();
    await tester.pumpWidget(ByteSqueezeApp(controller: controller));
    await tester.pumpAndSettle();

    expect(find.text('ByteSqueeze'), findsNothing);
    expect(find.text('Your media pipeline is under control.'), findsOneWidget);
    expect(find.text('Library'), findsOneWidget);
    expect(find.text('Autopilot'), findsOneWidget);
    expect(find.text('More'), findsOneWidget);
  });

  testWidgets('library exposes friendly Smart preview and season actions',
      (tester) async {
    final controller = AppController()..enterDemo();
    await tester.pumpWidget(ByteSqueezeApp(controller: controller));
    await tester.pumpAndSettle();

    await tester.tap(find.byIcon(Icons.video_library_outlined));
    await tester.pumpAndSettle();

    expect(find.text('Preview, tune, then queue'), findsOneWidget);
    expect(find.text('Best savings'), findsOneWidget);

    await tester.tap(find.text('Shows'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Foundation').first);
    await tester.pumpAndSettle();

    expect(find.text('Smart Queue Full Show'), findsOneWidget);
    expect(find.text('Preview real Smart encode'), findsOneWidget);
    expect(find.text('Preview or Smart Queue one complete season'),
        findsOneWidget);
    expect(find.text('Season 1'), findsOneWidget);
  });
}
