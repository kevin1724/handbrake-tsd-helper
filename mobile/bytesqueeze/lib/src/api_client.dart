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
  ByteSqueezeApi(this.store, {http.Client? client})
    : _http = client ?? http.Client();

  final SessionStore store;
  final http.Client _http;
  ServerSession? session;
  bool _refreshing = false;
  String _activeBaseUrl = '';

  String get activeBaseUrl =>
      _activeBaseUrl.isNotEmpty ? _activeBaseUrl : (session?.baseUrl ?? '');

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
    String fallbackBaseUrl = '',
    required String code,
    required String deviceName,
  }) async {
    final normalized = normalizeBaseUrl(baseUrl);
    final fallback = normalizeBaseUrl(fallbackBaseUrl);
    if (normalized.isEmpty) {
      throw const ApiFailure('Enter the address of your TSD server.');
    }
    final deviceId = await store.deviceId();
    final roots = <String>[
      normalized,
      if (fallback.isNotEmpty && fallback != normalized) fallback,
    ];
    Map<String, dynamic>? data;
    ApiFailure? lastFailure;
    for (final root in roots) {
      try {
        data = await _request(
          baseUrl: root,
          path: '/pair',
          method: 'POST',
          authenticated: false,
          body: {
            'code': code.trim().toUpperCase(),
            'device_id': deviceId,
            'device_name': deviceName.trim().isEmpty
                ? 'ByteSqueeze'
                : deviceName.trim(),
            'platform': 'android',
          },
        );
        _activeBaseUrl = root;
        break;
      } on ApiFailure catch (failure) {
        lastFailure = failure;
        if (failure.statusCode != null) rethrow;
      }
    }
    if (data == null) {
      throw lastFailure ??
          const ApiFailure('Could not reach either TSD address.');
    }
    final next = ServerSession(
      baseUrl: normalized,
      fallbackBaseUrl: fallback,
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
    final explicitRoot = normalizeBaseUrl(baseUrl ?? '');
    final roots = <String>[];
    void addRoot(String value) {
      final normalized = normalizeBaseUrl(value);
      if (normalized.isNotEmpty && !roots.contains(normalized)) {
        roots.add(normalized);
      }
    }

    if (explicitRoot.isNotEmpty) {
      addRoot(explicitRoot);
    } else {
      addRoot(_activeBaseUrl);
      addRoot(active?.baseUrl ?? '');
      addRoot(active?.fallbackBaseUrl ?? '');
    }
    if (roots.isEmpty) {
      throw const ApiFailure('ByteSqueeze is not connected to a server.');
    }
    ApiFailure? lastFailure;
    for (final root in roots) {
      try {
        return await _requestAt(
          root: root,
          path: path,
          method: method,
          body: body,
          authenticated: authenticated,
          timeout: timeout,
          retryAfterRefresh: retryAfterRefresh,
        );
      } on ApiFailure catch (failure) {
        lastFailure = failure;
        // HTTP responses prove this address is reachable. Do not mask a real
        // authentication or server error by trying another address.
        if (failure.statusCode != null) rethrow;
      }
    }
    throw lastFailure ??
        const ApiFailure('Could not reach either TSD address.');
  }

  Future<Map<String, dynamic>> _requestAt({
    required String root,
    required String path,
    required String method,
    Map<String, dynamic>? body,
    required bool authenticated,
    Duration? timeout,
    required bool retryAfterRefresh,
  }) async {
    final active = session;
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
          ? _http.post(
              uri,
              headers: headers,
              body: jsonEncode(body ?? <String, dynamic>{}),
            )
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
    _activeBaseUrl = root;
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
        path: '/token/refresh',
        method: 'POST',
        authenticated: false,
        retryAfterRefresh: false,
        body: {
          'device_id': active.deviceId,
          'refresh_token': active.refreshToken,
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
    _activeBaseUrl = '';
    await store.clear();
  }

  Future<ServerSession> updateAddresses({
    required String baseUrl,
    String fallbackBaseUrl = '',
  }) async {
    final active = session;
    if (active == null) {
      throw const ApiFailure('ByteSqueeze is not connected to a server.');
    }
    final primary = normalizeBaseUrl(baseUrl);
    final fallback = normalizeBaseUrl(fallbackBaseUrl);
    if (primary.isEmpty) {
      throw const ApiFailure('Enter the primary TSD address.');
    }
    final next = active.copyWith(baseUrl: primary, fallbackBaseUrl: fallback);
    session = next;
    if (_activeBaseUrl != primary && _activeBaseUrl != fallback) {
      _activeBaseUrl = primary;
    }
    await store.save(next);
    return next;
  }
}
