import 'package:bytesqueeze/main.dart';
import 'package:bytesqueeze/src/app_controller.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('demo opens the ByteSqueeze dashboard', (tester) async {
    final controller = AppController()..enterDemo();
    await tester.pumpWidget(ByteSqueezeApp(controller: controller));
    await tester.pumpAndSettle();

    expect(find.text('ByteSqueeze'), findsOneWidget);
    expect(find.text('Media operations are ready.'), findsOneWidget);
    expect(find.text('1 encoding now'), findsOneWidget);
    expect(find.text('Library'), findsOneWidget);
    expect(find.text('Automate'), findsOneWidget);
    expect(find.text('More'), findsOneWidget);
  });

  testWidgets('V3 command center exposes navigation and safe actions',
      (tester) async {
    final controller = AppController()..enterDemo();
    await tester.pumpWidget(ByteSqueezeApp(controller: controller));
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Command center'));
    await tester.pumpAndSettle();

    expect(find.text('Command center'), findsOneWidget);
    expect(find.text('Open Library'), findsOneWidget);
    await tester.scrollUntilVisible(
        find.text('Queue with Smart Presets'), 220,
        scrollable: find.byType(Scrollable).last);
    await tester.pumpAndSettle();
    expect(find.text('Queue with Smart Presets'), findsOneWidget);
  });

  testWidgets('settings keeps the V2 Classic fallback available',
      (tester) async {
    final controller = AppController()..enterDemo();
    await tester.pumpWidget(ByteSqueezeApp(controller: controller));
    await tester.pumpAndSettle();

    await tester.tap(find.byIcon(Icons.tune_outlined));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Interface & layout'), 220,
        scrollable: find.byType(Scrollable).first);
    await tester.tap(find.text('Interface & layout'));
    await tester.pumpAndSettle();

    expect(find.text('V3 Beta'), findsOneWidget);
    expect(find.text('V2 Classic'), findsOneWidget);
    await tester.tap(find.text('V2 Classic'));
    await tester.pumpAndSettle();
    expect(controller.useV3, isFalse);
    expect(await controller.store.loadInterfaceVersion(), 'v2');
  });

  testWidgets('mobile settings expose GPU slots and CPU exclusivity',
      (tester) async {
    final controller = AppController()..enterDemo();
    await tester.pumpWidget(ByteSqueezeApp(controller: controller));
    await tester.pumpAndSettle();

    await tester.tap(find.byIcon(Icons.tune_outlined));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
        find.text('Encoding capacity & safety'), 220,
        scrollable: find.byType(Scrollable).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Encoding capacity & safety'));
    await tester.pumpAndSettle();

    expect(find.text('Simultaneous hardware transcodes'), findsOneWidget);
    expect(find.textContaining('CPU/software encoding always stays at one'),
        findsOneWidget);
    expect(find.text('Stop unexpectedly large outputs'), findsOneWidget);
  });

  testWidgets('queue prioritizes running work and hardware capacity',
      (tester) async {
    final controller = AppController()..enterDemo();
    await tester.pumpWidget(ByteSqueezeApp(controller: controller));
    await tester.pumpAndSettle();

    await tester.tap(find.byIcon(Icons.motion_photos_on_outlined));
    await tester.pumpAndSettle();

    expect(find.text('Queue'), findsWidgets);
    expect(find.text('Running now'), findsOneWidget);
    expect(find.textContaining('GPU limit 2'), findsOneWidget);
    expect(find.text('Up next'), findsOneWidget);
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
    final foundation = find.text('Foundation').first;
    await tester.scrollUntilVisible(foundation, 260,
        scrollable: find.byType(Scrollable).first);
    await tester.pumpAndSettle();
    await tester.tap(foundation);
    await tester.pumpAndSettle();

    expect(find.byType(DraggableScrollableSheet), findsOneWidget);
    final detailsScroll = find
        .descendant(
          of: find.byType(DraggableScrollableSheet),
          matching: find.byType(Scrollable),
        )
        .first;
    await tester.scrollUntilVisible(find.text('Preview real Smart encode'), 220,
        scrollable: detailsScroll);
    expect(find.text('Preview real Smart encode'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('Smart Queue Full Show'), 220,
        scrollable: detailsScroll);
    expect(find.text('Smart Queue Full Show'), findsOneWidget);
    await tester.scrollUntilVisible(
        find.text('Preview or Smart Queue one complete season'), 220,
        scrollable: detailsScroll);
    expect(find.text('Preview or Smart Queue one complete season'),
        findsOneWidget);
    await tester.scrollUntilVisible(find.text('Season 1'), 220,
        scrollable: detailsScroll);
    expect(find.text('Season 1'), findsOneWidget);
  });
}
