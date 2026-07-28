import 'package:bytesqueeze/src/api_client.dart';
import 'package:bytesqueeze/src/session_store.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

ServerSession _session() => const ServerSession(
  baseUrl: 'http://192.168.1.50:8080',
  fallbackBaseUrl: 'http://100.90.80.70:8080',
  deviceId: 'phone',
  deviceName: 'ByteSqueeze phone',
  scope: 'control',
  accessToken: 'access',
  refreshToken: 'refresh',
);

void main() {
  test('connection failure switches to the Tailscale fallback', () async {
    final requestedHosts = <String>[];
    final client = MockClient((request) async {
      requestedHosts.add(request.url.host);
      if (request.url.host == '192.168.1.50') {
        throw http.ClientException('home route offline', request.url);
      }
      return http.Response(
        '{"ok":true}',
        200,
        headers: {'content-type': 'application/json'},
      );
    });
    final api = ByteSqueezeApi(SessionStore(), client: client)
      ..session = _session();

    final result = await api.get('/dashboard');

    expect(result['ok'], isTrue);
    expect(requestedHosts, ['192.168.1.50', '100.90.80.70']);
    expect(api.activeBaseUrl, 'http://100.90.80.70:8080');
  });

  test('real HTTP errors are not hidden by address fallback', () async {
    final requestedHosts = <String>[];
    final client = MockClient((request) async {
      requestedHosts.add(request.url.host);
      return http.Response(
        '{"error":"server rejected request"}',
        500,
        headers: {'content-type': 'application/json'},
      );
    });
    final api = ByteSqueezeApi(SessionStore(), client: client)
      ..session = _session();

    await expectLater(
      api.get('/dashboard'),
      throwsA(
        isA<ApiFailure>().having(
          (failure) => failure.statusCode,
          'statusCode',
          500,
        ),
      ),
    );
    expect(requestedHosts, ['192.168.1.50']);
  });
}
