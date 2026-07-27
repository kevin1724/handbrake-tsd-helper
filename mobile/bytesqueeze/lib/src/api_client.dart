import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'session_store.dart';

class ApiFailure implements Exception {
  const ApiFailure(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

class ByteSqueezeApi {
  ByteSqueezeApi(this.store);

  final SessionStore store;
  final http.Client _http = http.Client();
  ServerSession? session;
  bool _refreshing = false;

  String normalizeBaseUrl(String value) {
    var cleaned = value.trim();
    if (cleaned.isEmpty) return cleaned;
    if (!cleaned.startsWith('http://') && !cleaned.startsWith('https://')) {
      cleaned = 'http://$cleaned';
    }
    return cleaned.replaceAll(RegExp(r'/+$'), '');
  }

  Future<Map<String, dynamic>> discover(String baseUrl) async {
    return _request(
      baseUrl: normalizeBaseUrl(baseUrl),
      path: '/discovery',
      authenticated: false,
      timeout: const Duration(seconds: 12),
    );
  }

  Future<ServerSession> pair({
    required String baseUrl,
    required String code,
    required String deviceName,
  }) async {
    final normalized = normalizeBaseUrl(baseUrl);
    if (normalized.isEmpty) {
      throw const ApiFailure('Enter the address of your TSD server.');
    }
    final deviceId = await store.deviceId();
    final data = await _request(
      baseUrl: normalized,
      path: '/pair',
      method: 'POST',
      authenticated: false,
      body: {
        'code': code.trim().toUpperCase(),
        'device_id': deviceId,
        'device_name':
            deviceName.trim().isEmpty ? 'ByteSqueeze' : deviceName.trim(),
        'platform': 'android',
      },
    );
    final next = ServerSession(
      baseUrl: normalized,
      deviceId: '${data['device_id'] ?? deviceId}',
      deviceName: '${data['device_name'] ?? deviceName}',
      scope: '${data['scope'] ?? 'read'}',
      accessToken: '${data['access_token'] ?? ''}',
      refreshToken: '${data['refresh_token'] ?? ''}',
    );
    if (next.accessToken.isEmpty || next.refreshToken.isEmpty) {
      throw const ApiFailure('The server did not return mobile credentials.');
    }
    session = next;
    await store.save(next);
    return next;
  }

  Future<Map<String, dynamic>> get(String path, {Duration? timeout}) {
    return _request(path: path, timeout: timeout);
  }

  Future<Map<String, dynamic>> post(
    String path,
    Map<String, dynamic>? body, {
    Duration? timeout,
  }) {
    return _request(path: path, method: 'POST', body: body, timeout: timeout);
  }

  Future<Map<String, dynamic>> _request({
    String? baseUrl,
    required String path,
    String method = 'GET',
    Map<String, dynamic>? body,
    bool authenticated = true,
    Duration? timeout,
    bool retryAfterRefresh = true,
  }) async {
    final active = session;
    final root = normalizeBaseUrl(baseUrl ?? active?.baseUrl ?? '');
    if (root.isEmpty) {
      throw const ApiFailure('ByteSqueeze is not connected to a server.');
    }
    final uri = Uri.parse('$root/api/mobile/v1$path');
    final headers = <String, String>{'Accept': 'application/json'};
    if (body != null) {
      headers['Content-Type'] = 'application/json';
    }
    if (authenticated && active != null) {
      headers['Authorization'] = 'Bearer ${active.accessToken}';
    }

    http.Response response;
    try {
      final future = method == 'POST'
          ? _http.post(uri,
              headers: headers, body: jsonEncode(body ?? <String, dynamic>{}))
          : _http.get(uri, headers: headers);
      response = await future.timeout(timeout ?? const Duration(seconds: 24));
    } on TimeoutException {
      throw const ApiFailure('The TSD server took too long to respond.');
    } catch (error) {
      throw ApiFailure('Could not reach the TSD server: $error');
    }

    Map<String, dynamic> data;
    try {
      final decoded = jsonDecode(response.body);
      data = decoded is Map<String, dynamic>
          ? decoded
          : <String, dynamic>{'data': decoded};
    } catch (_) {
      data = <String, dynamic>{};
    }

    if (response.statusCode == 401 &&
        authenticated &&
        retryAfterRefresh &&
        await _refresh()) {
      return _request(
        path: path,
        method: method,
        body: body,
        authenticated: authenticated,
        timeout: timeout,
        retryAfterRefresh: false,
      );
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiFailure(
        '${data['error'] ?? data['message'] ?? 'Server request failed'}',
        statusCode: response.statusCode,
      );
    }
    return data;
  }

  Future<bool> _refresh() async {
    final active = session;
    if (active == null || active.refreshToken.isEmpty || _refreshing) {
      return false;
    }
    _refreshing = true;
    try {
      final data = await _request(
        baseUrl: active.baseUrl,
        path: '/token/refresh',
        method: 'POST',
        authenticated: false,
        retryAfterRefresh: false,
        body: {
          'device_id': active.deviceId,
          'refresh_token': active.refreshToken
        },
      );
      final next = active.copyWith(
        accessToken: '${data['access_token'] ?? ''}',
        refreshToken: '${data['refresh_token'] ?? ''}',
        scope: '${data['scope'] ?? active.scope}',
      );
      if (next.accessToken.isEmpty || next.refreshToken.isEmpty) {
        return false;
      }
      session = next;
      await store.save(next);
      return true;
    } catch (_) {
      return false;
    } finally {
      _refreshing = false;
    }
  }

  Future<void> disconnect() async {
    session = null;
    await store.clear();
  }
}
