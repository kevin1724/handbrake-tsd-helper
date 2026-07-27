import 'package:bytesqueeze/main.dart';
import 'package:bytesqueeze/src/app_controller.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('demo opens the ByteSqueeze dashboard', (tester) async {
    final controller = AppController()..enterDemo();
    await tester.pumpWidget(ByteSqueezeApp(controller: controller));
    await tester.pumpAndSettle();

    expect(find.text('ByteSqueeze'), findsOneWidget);
    expect(find.text('Your media pipeline is under control.'), findsOneWidget);
    expect(find.text('Library'), findsOneWidget);
    expect(find.text('Automation'), findsOneWidget);
  });
}
