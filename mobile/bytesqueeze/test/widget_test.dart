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
    expect(find.text('Automate'), findsOneWidget);
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
    final foundation = find.text('Foundation').first;
    await tester.ensureVisible(foundation);
    await tester.pumpAndSettle();
    final foundationCard = find
        .ancestor(of: foundation, matching: find.byType(InkWell))
        .first;
    await tester.tap(foundationCard);
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
