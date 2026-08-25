import 'package:bytesqueeze/src/api_client.dart';
import 'package:bytesqueeze/src/app_controller.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Size Wizard automatic estimates react to media choices', () async {
    final controller = AppController()..enterDemo();

    final balanced = await controller.planSizeWizard('/demo/Arrival.mkv');
    final smaller = await controller.planSizeWizard(
      '/demo/Arrival.mkv',
      options: {
        'target_size_auto': true,
        'quality': 'small',
        'video_codec': 'av1',
        'resolution_mode': '720',
      },
    );

    final balancedMb =
        ((balanced['plan'] as Map)['inputs'] as Map)['target_mb'] as num;
    final smallerMb =
        ((smaller['plan'] as Map)['inputs'] as Map)['target_mb'] as num;
    expect(balancedMb, isNot(5120));
    expect(smallerMb, lessThan(balancedMb));
    expect(
      (((smaller['plan'] as Map)['estimates'] as Map)['auto_target']
          as Map)['mode'],
      'source_aware',
    );
  });

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
