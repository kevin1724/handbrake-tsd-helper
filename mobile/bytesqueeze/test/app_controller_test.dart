import 'package:bytesqueeze/src/api_client.dart';
import 'package:bytesqueeze/src/app_controller.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('older servers do not trigger a global connection failure', () async {
    final controller = AppController();
    controller.api = _LegacyServerApi(controller.store);

    await controller.refreshAll(notifyBusy: false);

    expect(controller.error, isNull);
    expect(controller.serverSupportsOperationsSettings, isFalse);
    expect(controller.operations['hardware_transcode_concurrency'], 3);
    expect(controller.dashboard['ok'], isTrue);
  });
}

class _LegacyServerApi extends ByteSqueezeApi {
  _LegacyServerApi(super.store);

  @override
  Future<Map<String, dynamic>> get(String path, {Duration? timeout}) async {
    if (path == '/operations') {
      throw const ApiFailure(
        'This app feature is not available on the connected server yet.',
        statusCode: 404,
      );
    }
    if (path == '/jobs') {
      return {
        'ok': true,
        'summary': {'hardware_transcode_concurrency': 3},
      };
    }
    if (path == '/library') return {'ok': true, 'library': {}};
    if (path.startsWith('/calendar')) return {'ok': true, 'calendar': {}};
    if (path == '/autopilot/review') return {'ok': true, 'review': {}};
    return {'ok': true};
  }
}
