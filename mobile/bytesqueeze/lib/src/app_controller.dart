import 'package:flutter/foundation.dart';

import 'api_client.dart';
import 'demo_data.dart';
import 'session_store.dart';

class AppController extends ChangeNotifier {
  AppController() : store = SessionStore() {
    api = ByteSqueezeApi(store);
  }

  final SessionStore store;
  late ByteSqueezeApi api;

  bool booting = true;
  bool busy = false;
  bool demoMode = false;
  String? error;
  int selectedTab = 0;
  ServerSession? session;

  Map<String, dynamic> dashboard = {};
  Map<String, dynamic> jobs = {};
  Map<String, dynamic> library = {};
  Map<String, dynamic> calendar = {};
  Map<String, dynamic> automation = {};
  Map<String, dynamic> nodes = {};
  Map<String, dynamic> storage = {};
  Map<String, dynamic> events = {};
  Map<String, dynamic> smartPresets = {};
  Map<String, dynamic> autopilotReview = {};

  bool get connected => demoMode || session != null;
  bool get canControl => demoMode || session?.canControl == true;
  String get serverLabel =>
      demoMode ? 'Demo server' : (api.activeBaseUrl.isEmpty ? 'Not connected' : api.activeBaseUrl);

  Future<void> bootstrap() async {
    booting = true;
    notifyListeners();
    session = await store.load();
    api.session = session;
    if (session != null) {
      try {
        await refreshAll(notifyBusy: false);
      } catch (_) {
        // Keep the saved session. The shell can show offline data and retry.
      }
    }
    booting = false;
    notifyListeners();
  }

  Future<void> pair(
      {required String baseUrl,
      String fallbackBaseUrl = '',
      required String code,
      required String deviceName}) async {
    busy = true;
    error = null;
    notifyListeners();
    try {
      session =
          await api.pair(baseUrl: baseUrl, fallbackBaseUrl: fallbackBaseUrl, code: code, deviceName: deviceName);
      demoMode = false;
      await refreshAll(notifyBusy: false);
    } catch (failure) {
      error = _message(failure);
      rethrow;
    } finally {
      busy = false;
      notifyListeners();
    }
  }

  void enterDemo() {
    booting = false;
    demoMode = true;
    session = null;
    api.session = null;
    dashboard = DemoData.dashboard;
    jobs = DemoData.jobs;
    library = DemoData.library;
    calendar = DemoData.calendar;
    automation = DemoData.automation;
    nodes = DemoData.nodes;
    storage = DemoData.storage;
    events = DemoData.events;
    smartPresets = DemoData.smart;
    autopilotReview = {};
    error = null;
    notifyListeners();
  }

  Future<void> disconnect() async {
    await api.disconnect();
    session = null;
    demoMode = false;
    selectedTab = 0;
    dashboard = {};
    jobs = {};
    library = {};
    calendar = {};
    automation = {};
    nodes = {};
    storage = {};
    events = {};
    smartPresets = {};
    autopilotReview = {};
    notifyListeners();
  }

  void selectTab(int value) {
    selectedTab = value;
    notifyListeners();
  }

  Future<void> refreshAll({bool notifyBusy = true}) async {
    if (demoMode) {
      enterDemo();
      return;
    }
    if (notifyBusy) {
      busy = true;
      notifyListeners();
    }
    error = null;
    final failures = <String>[];
    await Future.wait([
      _load('/dashboard', (value) => dashboard = value, failures),
      _load('/jobs', (value) => jobs = value, failures),
      _load('/library', (value) => library = _map(value['library']), failures),
      _load('/calendar?days=180', (value) => calendar = _map(value['calendar']),
          failures),
      _load('/automation', (value) => automation = value, failures),
      _load('/nodes', (value) => nodes = value, failures),
      _load('/storage?limit=100', (value) => storage = value, failures),
      _load('/events?limit=100', (value) => events = value, failures),
      _load('/smart_presets', (value) => smartPresets = value, failures),
      _load('/autopilot/review',
          (value) => autopilotReview = _map(value['review']), failures),
    ]);
    if (failures.isNotEmpty) error = failures.first;
    busy = false;
    notifyListeners();
  }

  Future<void> _load(
    String path,
    void Function(Map<String, dynamic>) apply,
    List<String> failures,
  ) async {
    try {
      apply(await api.get(path));
    } catch (failure) {
      failures.add(_message(failure));
    }
  }

  Future<void> setQueuePaused(bool paused) async {
    _requireControl();
    if (demoMode) {
      jobs['paused'] = paused;
      _map(dashboard['queue'])['paused'] = paused;
      notifyListeners();
      return;
    }
    await api.post('/queue', {'paused': paused});
    await refreshJobsAndDashboard();
  }

  Future<void> jobAction(String jobId, String action, {int? position}) async {
    _requireControl();
    if (demoMode) {
      final rows = _list(jobs['jobs']);
      if (action == 'cancel' || action == 'remove') {
        rows.removeWhere((row) => _map(row)['id'] == jobId);
        jobs['jobs'] = rows;
      }
      notifyListeners();
      return;
    }
    await api.post('/jobs/$jobId/action',
        {'action': action, if (position != null) 'position': position});
    await refreshJobsAndDashboard();
  }

  Future<void> clearJobs(String target) async {
    _requireControl();
    if (demoMode) {
      final terminal = {'done', 'error', 'canceled'};
      final rows = _list(jobs['jobs']);
      rows.removeWhere((row) {
        final status = '${_map(row)['status'] ?? ''}';
        return target == 'finished'
            ? terminal.contains(status)
            : status == 'queued';
      });
      jobs['jobs'] = rows;
      notifyListeners();
      return;
    }
    await api.post('/jobs/clear', {'target': target});
    await refreshJobsAndDashboard();
  }

  Future<void> refreshJobsAndDashboard() async {
    if (demoMode) return;
    final values = await Future.wait([api.get('/jobs'), api.get('/dashboard')]);
    jobs = values[0];
    dashboard = values[1];
    notifyListeners();
  }

  Future<void> refreshLibrary() async {
    _requireControl();
    if (demoMode) return;
    busy = true;
    notifyListeners();
    try {
      final value = await api.post('/library/refresh', {},
          timeout: const Duration(minutes: 3));
      library = _map(value['library']);
      dashboard = await api.get('/dashboard');
    } finally {
      busy = false;
      notifyListeners();
    }
  }

  Future<void> queuePaths(
    List<String> paths, {
    String preset = 'smart',
    String mode = 'local',
    String? nodeId,
  }) async {
    _requireControl();
    if (paths.isEmpty) {
      throw const ApiFailure('No media files are available to queue.');
    }
    if (demoMode) return;
    await api.post(
        '/library/queue',
        {
          'paths': paths,
          'preset': preset,
          'mode': mode,
          if (nodeId != null && nodeId.isNotEmpty) 'node_id': nodeId,
        },
        timeout: const Duration(minutes: 2));
    await refreshJobsAndDashboard();
  }

  Future<void> trackShow(Map<String, dynamic> show, bool tracked) async {
    _requireControl();
    show['tracked'] = tracked;
    notifyListeners();
    if (demoMode) return;
    final files = _list(show['files'])
        .map((row) => '${_map(row)['path'] ?? ''}')
        .where((path) => path.isNotEmpty)
        .toList();
    await api.post('/library/tracked_show', {
      'show_id': show['id'],
      'title': show['title'],
      'year': show['year'],
      'tmdb_id': show['tmdb_id'],
      'tvmaze_id': show['tvmaze_id'],
      'poster_url': show['poster_url'],
      'paths': files,
      'tracked': tracked,
      'monitor_releases': show['monitor_releases'] != false,
      'auto_queue': show['auto_queue_downloads'] != false,
    });
    if (!demoMode) {
      final value = await api.get('/calendar?days=180');
      calendar = _map(value['calendar']);
      notifyListeners();
    }
  }

  Future<void> saveAutomation(Map<String, dynamic> updates) async {
    _requireControl();
    if (demoMode) {
      _map(automation['settings']).addAll(updates);
      notifyListeners();
      return;
    }
    automation = await api.post('/automation', {'action': 'save', ...updates});
    dashboard = await api.get('/dashboard');
    notifyListeners();
  }

  Future<void> runAutopilot() async {
    _requireControl();
    if (demoMode) return;
    busy = true;
    notifyListeners();
    try {
      automation = await api.post('/automation', {'action': 'run'},
          timeout: const Duration(minutes: 3));
      dashboard = await api.get('/dashboard');
      final value = await api.post('/autopilot/review', {});
      autopilotReview = _map(value['review']);
      _pollAutopilotReview();
    } finally {
      busy = false;
      notifyListeners();
    }
  }

  Future<void> saveSmartProfile(Map<String, dynamic> profile) async {
    _requireControl();
    if (demoMode) {
      smartPresets['profile'] = profile;
      notifyListeners();
      return;
    }
    smartPresets = await api.post('/smart_presets', {'profile': profile});
    notifyListeners();
  }

  Future<void> startAutopilotReview({bool next = false}) async {
    _requireControl();
    if (demoMode) return;
    final value = await api.post('/autopilot/review', {'next': next});
    autopilotReview = _map(value['review']);
    notifyListeners();
    _pollAutopilotReview();
  }

  Future<void> refreshAutopilotReview() async {
    if (demoMode) return;
    final value = await api.get('/autopilot/review');
    autopilotReview = _map(value['review']);
    notifyListeners();
  }

  Future<void> submitAutopilotReview(String verdict, String reason) async {
    _requireControl();
    if (demoMode) return;
    final value = await api.post('/autopilot/review/feedback', {
      'verdict': verdict,
      'reason': reason,
    });
    autopilotReview = _map(value['review']);
    smartPresets = await api.get('/smart_presets');
    automation = await api.get('/automation');
    notifyListeners();
  }

  Future<void> _pollAutopilotReview() async {
    for (var attempt = 0; attempt < 240; attempt++) {
      await Future<void>.delayed(const Duration(milliseconds: 1400));
      if (demoMode || session == null) return;
      try {
        final value = await api.get('/autopilot/review');
        autopilotReview = _map(value['review']);
        notifyListeners();
        final preview = _map(autopilotReview['preview']);
        final state = '${preview['state'] ?? ''}';
        if (state == 'done' || state == 'error' || state == 'expired') return;
      } catch (_) {
        return;
      }
    }
  }

  Future<void> updateServerAddresses(String primary, String fallback) async {
    if (demoMode) return;
    session = await api.updateAddresses(baseUrl: primary, fallbackBaseUrl: fallback);
    notifyListeners();
    await refreshAll();
  }

  void _requireControl() {
    if (!canControl) {
      throw const ApiFailure('This device was paired with read-only access.');
    }
  }

  String _message(Object failure) =>
      failure is ApiFailure ? failure.message : '$failure';

  static Map<String, dynamic> _map(dynamic value) {
    return value is Map<String, dynamic> ? value : <String, dynamic>{};
  }

  static List<dynamic> _list(dynamic value) =>
      value is List ? value : <dynamic>[];
}
