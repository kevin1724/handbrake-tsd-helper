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
    expect(find.text('Media operations are ready.'), findsOneWidget);
    expect(find.text('1 encoding now'), findsOneWidget);
    expect(find.text('Library'), findsOneWidget);
    expect(find.text('Automate'), findsOneWidget);
    expect(find.text('More'), findsOneWidget);
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
