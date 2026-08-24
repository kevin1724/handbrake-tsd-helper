import 'dart:math';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

class ServerSession {
  const ServerSession({
    required this.baseUrl,
    this.fallbackBaseUrl = '',
    required this.deviceId,
    required this.deviceName,
    required this.scope,
    required this.accessToken,
    required this.refreshToken,
  });

  final String baseUrl;
  final String fallbackBaseUrl;
  final String deviceId;
  final String deviceName;
  final String scope;
  final String accessToken;
  final String refreshToken;

  bool get canControl => scope == 'control';

  ServerSession copyWith({
    String? baseUrl,
    String? fallbackBaseUrl,
    String? accessToken,
    String? refreshToken,
    String? scope,
  }) {
    return ServerSession(
      baseUrl: baseUrl ?? this.baseUrl,
      fallbackBaseUrl: fallbackBaseUrl ?? this.fallbackBaseUrl,
      deviceId: deviceId,
      deviceName: deviceName,
      scope: scope ?? this.scope,
      accessToken: accessToken ?? this.accessToken,
      refreshToken: refreshToken ?? this.refreshToken,
    );
  }
}

class SessionStore {
  static const _secure = FlutterSecureStorage(
    aOptions: AndroidOptions(),
  );

  static const _serverKey = 'bytesqueeze.server_url';
  static const _fallbackServerKey = 'bytesqueeze.fallback_server_url';
  static const _deviceIdKey = 'bytesqueeze.device_id';
  static const _deviceNameKey = 'bytesqueeze.device_name';
  static const _scopeKey = 'bytesqueeze.scope';
  static const _accessKey = 'bytesqueeze.access_token';
  static const _refreshKey = 'bytesqueeze.refresh_token';
  static const _interfaceVersionKey = 'bytesqueeze.interface_version';
  static const _interfaceDensityKey = 'bytesqueeze.interface_density';
  static const _showSecondaryUiKey = 'bytesqueeze.ui.show_secondary';
  static const _showStatsForNerdsKey = 'bytesqueeze.ui.stats_for_nerds';

  Future<String> loadInterfaceVersion() async {
    final prefs = await SharedPreferences.getInstance();
    final value = (prefs.getString(_interfaceVersionKey) ?? 'v3').toLowerCase();
    return value == 'v2' ? 'v2' : 'v3';
  }

  Future<String> loadInterfaceDensity() async {
    final prefs = await SharedPreferences.getInstance();
    final value =
        (prefs.getString(_interfaceDensityKey) ?? 'comfortable').toLowerCase();
    return value == 'compact' ? 'compact' : 'comfortable';
  }

  Future<void> saveInterfacePreferences({
    required String version,
    required String density,
  }) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_interfaceVersionKey, version == 'v2' ? 'v2' : 'v3');
    await prefs.setString(
      _interfaceDensityKey,
      density == 'compact' ? 'compact' : 'comfortable',
    );
  }

  Future<bool> loadShowSecondaryUi() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(_showSecondaryUiKey) ?? false;
  }

  Future<bool> loadStatsForNerds() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(_showStatsForNerdsKey) ?? false;
  }

  Future<void> saveUiVisibility({
    bool? showSecondaryUi,
    bool? statsForNerds,
  }) async {
    final prefs = await SharedPreferences.getInstance();
    if (showSecondaryUi != null) {
      await prefs.setBool(_showSecondaryUiKey, showSecondaryUi);
    }
    if (statsForNerds != null) {
      await prefs.setBool(_showStatsForNerdsKey, statsForNerds);
    }
  }

  Future<ServerSession?> load() async {
    final prefs = await SharedPreferences.getInstance();
    final baseUrl = prefs.getString(_serverKey) ?? '';
    final fallbackBaseUrl = prefs.getString(_fallbackServerKey) ?? '';
    final deviceId = prefs.getString(_deviceIdKey) ?? '';
    final deviceName = prefs.getString(_deviceNameKey) ?? 'ByteSqueeze';
    final scope = prefs.getString(_scopeKey) ?? 'read';
    final access = await _secure.read(key: _accessKey) ?? '';
    final refresh = await _secure.read(key: _refreshKey) ?? '';
    if (baseUrl.isEmpty ||
        deviceId.isEmpty ||
        access.isEmpty ||
        refresh.isEmpty) {
      return null;
    }
    return ServerSession(
      baseUrl: baseUrl,
      fallbackBaseUrl: fallbackBaseUrl,
      deviceId: deviceId,
      deviceName: deviceName,
      scope: scope,
      accessToken: access,
      refreshToken: refresh,
    );
  }

  Future<void> save(ServerSession session) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_serverKey, session.baseUrl);
    await prefs.setString(_fallbackServerKey, session.fallbackBaseUrl);
    await prefs.setString(_deviceIdKey, session.deviceId);
    await prefs.setString(_deviceNameKey, session.deviceName);
    await prefs.setString(_scopeKey, session.scope);
    await _secure.write(key: _accessKey, value: session.accessToken);
    await _secure.write(key: _refreshKey, value: session.refreshToken);
  }

  Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_serverKey);
    await prefs.remove(_fallbackServerKey);
    await prefs.remove(_scopeKey);
    await _secure.delete(key: _accessKey);
    await _secure.delete(key: _refreshKey);
  }

  Future<String> deviceId() async {
    final prefs = await SharedPreferences.getInstance();
    final existing = prefs.getString(_deviceIdKey);
    if (existing != null && existing.isNotEmpty) return existing;
    final random = Random.secure();
    final value =
        List.generate(24, (_) => random.nextInt(16).toRadixString(16)).join();
    await prefs.setString(_deviceIdKey, value);
    return value;
  }
}
