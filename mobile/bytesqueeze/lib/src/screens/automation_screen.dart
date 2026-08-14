import 'dart:convert';

import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../theme.dart';
import '../widgets/common.dart';

class AutomationScreen extends StatefulWidget {
  const AutomationScreen({super.key, required this.controller});

  final AppController controller;

  @override
  State<AutomationScreen> createState() => _AutomationScreenState();
}

class _AutomationScreenState extends State<AutomationScreen> {
  bool _hydrated = false;
  bool _enabled = false;
  String _mode = 'observe';
  bool _movies = true;
  bool _shows = false;
  double _minSize = 2;
  double _minSavings = 10;
  double _batchLimit = 3;
  double _maxActive = 5;
  String _start = '00:00';
  String _end = '23:59';
  bool _scanEnabled = false;
  bool _continuousLearning = true;
  double _stabilityMinutes = 10;
  bool _saving = false;
  bool _tourScheduled = false;

  void _hydrate() {
    final settings = asMap(widget.controller.automation['settings']);
    if (settings.isEmpty) return;
    _enabled = settings['autopilot_enabled'] == true;
    _mode = '${settings['autopilot_mode'] ?? 'observe'}';
    _movies = settings['autopilot_include_movies'] != false;
    _shows = settings['autopilot_include_shows'] == true;
    _minSize = (settings['autopilot_min_size_gb'] as num?)?.toDouble() ?? 2;
    _minSavings =
        (settings['autopilot_min_savings_percent'] as num?)?.toDouble() ?? 10;
    _batchLimit = (settings['autopilot_batch_limit'] as num?)?.toDouble() ?? 3;
    _maxActive =
        (settings['autopilot_max_active_jobs'] as num?)?.toDouble() ?? 5;
    _start = '${settings['autopilot_schedule_start'] ?? '00:00'}';
    _end = '${settings['autopilot_schedule_end'] ?? '23:59'}';
    _scanEnabled = settings['beta_auto_scan_enabled'] == true;
    _continuousLearning =
        settings['autopilot_continuous_learning_enabled'] != false;
    _stabilityMinutes =
        (settings['beta_auto_scan_file_stability_minutes'] as num?)
                ?.toDouble() ??
            10;
    _hydrated = true;
  }

  @override
  Widget build(BuildContext context) {
    if (!_hydrated) _hydrate();
    final status = asMap(widget.controller.automation['status']);
    final onboarding = asMap(status['onboarding']);
    final autopilot = asMap(status['autopilot']);
    final readiness = asMap(status['readiness']);
    final continuousLearning = asMap(status['continuous_learning']);
    final checks = asList(readiness['checks']);
    final decisions = asList(autopilot['decisions']);
    final smartProfile = asMap(widget.controller.smartPresets['profile']);
    final learning = asMap(widget.controller.smartPresets['learning']);
    final ready = readiness['ready'] == true;
    if (!_tourScheduled &&
        !widget.controller.demoMode &&
        onboarding['tour_completed'] != true) {
      _tourScheduled = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _showTour();
      });
    }

    return RefreshIndicator(
      onRefresh: widget.controller.refreshAll,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        children: [
          PageInsets(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text('SELF-RUNNING ENCODING',
                              style: TextStyle(
                                  color: ByteSqueezeColors.cyan,
                                  fontSize: 11,
                                  fontWeight: FontWeight.w800,
                                  letterSpacing: 1.6)),
                          const SizedBox(height: 5),
                          Text('Autopilot',
                              style: Theme.of(context).textTheme.headlineLarge),
                          const SizedBox(height: 4),
                          const Text(
                              'Bounded, explainable decisions from your TSD server',
                              style: TextStyle(color: ByteSqueezeColors.muted)),
                        ],
                      ),
                    ),
                    StatusPill(
                      label: ready ? 'Ready' : 'Needs setup',
                      color: ready
                          ? ByteSqueezeColors.mint
                          : ByteSqueezeColors.amber,
                      icon: ready
                          ? Icons.verified_rounded
                          : Icons.build_circle_outlined,
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                _AutopilotGuideCard(
                  onProfile: _applyProfile,
                  enabled: widget.controller.canControl,
                  onTour: _restartTour,
                  onGuide: _showGuide,
                ),
                const SizedBox(height: 14),
                _AutopilotTrainingCard(controller: widget.controller),
                const SizedBox(height: 14),
                _CompletedFeedbackCard(
                    controller: widget.controller,
                    learning: continuousLearning),
                const SizedBox(height: 14),
                SurfaceCard(
                  gradient: const LinearGradient(
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                    colors: [Color(0xFF16356A), Color(0xFF0A1730)],
                  ),
                  borderColor: const Color(0xFF285C9E),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Row(
                        children: [
                          const DecoratedBox(
                            decoration: BoxDecoration(
                                color: Color(0x2231D6FF),
                                shape: BoxShape.circle),
                            child: Padding(
                                padding: EdgeInsets.all(12),
                                child: Icon(Icons.auto_awesome_rounded,
                                    color: ByteSqueezeColors.cyan)),
                          ),
                          const SizedBox(width: 13),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('Autopilot',
                                    style:
                                        Theme.of(context).textTheme.titleLarge),
                                Text(
                                    _enabled
                                        ? (_mode == 'manage'
                                            ? 'Managing eligible work'
                                            : 'Observing without queue changes')
                                        : 'Disabled',
                                    style: const TextStyle(
                                        color: ByteSqueezeColors.muted)),
                              ],
                            ),
                          ),
                          Switch.adaptive(
                              value: _enabled,
                              onChanged: widget.controller.canControl
                                  ? (value) => setState(() => _enabled = value)
                                  : null),
                        ],
                      ),
                      const SizedBox(height: 18),
                      Row(
                        children: [
                          _MiniMetric(
                              label: 'Eligible',
                              value: '${autopilot['eligible'] ?? 0}'),
                          _MiniMetric(
                              label: 'Selected',
                              value: '${autopilot['selected'] ?? 0}'),
                          _MiniMetric(
                              label: 'Capacity',
                              value: '${autopilot['capacity'] ?? 0}'),
                        ],
                      ),
                      const SizedBox(height: 18),
                      FilledButton.icon(
                        onPressed: widget.controller.canControl &&
                                !widget.controller.busy
                            ? () => _run(widget.controller.runAutopilot,
                                success: 'Autopilot cycle completed.')
                            : null,
                        icon: widget.controller.busy
                            ? const SizedBox(
                                width: 18,
                                height: 18,
                                child:
                                    CircularProgressIndicator(strokeWidth: 2))
                            : const Icon(Icons.play_arrow_rounded),
                        label: const Text('Run decision cycle now'),
                      ),
                    ],
                  ),
                ),
                const SectionHeader(
                    title: 'Operating policy',
                    subtitle:
                        'Observe first, then allow bounded queue management'),
                SurfaceCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      DropdownButtonFormField<String>(
                        initialValue: _mode,
                        decoration: const InputDecoration(
                            labelText: 'Mode',
                            prefixIcon: Icon(Icons.shield_outlined)),
                        items: const [
                          DropdownMenuItem(
                              value: 'observe',
                              child: Text('Observe · explain only')),
                          DropdownMenuItem(
                              value: 'manage',
                              child: Text('Manage · queue within limits')),
                        ],
                        onChanged: widget.controller.canControl
                            ? (value) =>
                                setState(() => _mode = value ?? 'observe')
                            : null,
                      ),
                      const SizedBox(height: 12),
                      SwitchListTile.adaptive(
                        contentPadding: EdgeInsets.zero,
                        value: _movies,
                        onChanged: widget.controller.canControl
                            ? (value) => setState(() => _movies = value)
                            : null,
                        title: const Text('Include movies'),
                        subtitle: const Text(
                            'Evaluate stable movie files against this policy.'),
                        secondary: const Icon(Icons.movie_outlined),
                      ),
                      SwitchListTile.adaptive(
                        contentPadding: EdgeInsets.zero,
                        value: _shows,
                        onChanged: widget.controller.canControl
                            ? (value) => setState(() => _shows = value)
                            : null,
                        title: const Text('Include shows'),
                        subtitle: const Text(
                            'Evaluate episodes in mapped Shows folders.'),
                        secondary: const Icon(Icons.tv_rounded),
                      ),
                      SwitchListTile.adaptive(
                        contentPadding: EdgeInsets.zero,
                        value: _scanEnabled,
                        onChanged: widget.controller.canControl
                            ? (value) => setState(() => _scanEnabled = value)
                            : null,
                        title: const Text('Watch mapped drives'),
                        subtitle: const Text(
                            'Incrementally discover new and changed downloads.'),
                        secondary: const Icon(Icons.radar_rounded),
                      ),
                      SwitchListTile.adaptive(
                        contentPadding: EdgeInsets.zero,
                        value: _continuousLearning,
                        onChanged: widget.controller.canControl
                            ? (value) => setState(
                                () => _continuousLearning = value)
                            : null,
                        title: const Text('Continue learning after playback'),
                        subtitle: const Text(
                            'Ask how completed learned encodes actually looked and sounded.'),
                        secondary: const Icon(Icons.rate_review_outlined),
                      ),
                      _SliderSetting(
                        label: 'Download write-safety window',
                        valueLabel: '${_stabilityMinutes.round()} min',
                        value: _stabilityMinutes,
                        min: 1,
                        max: 60,
                        divisions: 59,
                        enabled: widget.controller.canControl,
                        onChanged: (value) =>
                            setState(() => _stabilityMinutes = value),
                      ),
                      _SliderSetting(
                        label: 'Minimum source size',
                        valueLabel: '${_minSize.toStringAsFixed(1)} GB',
                        value: _minSize,
                        min: .1,
                        max: 20,
                        divisions: 199,
                        enabled: widget.controller.canControl,
                        onChanged: (value) => setState(() => _minSize = value),
                      ),
                      _SliderSetting(
                        label: 'Minimum estimated savings',
                        valueLabel: '${_minSavings.round()}%',
                        value: _minSavings,
                        min: 0,
                        max: 80,
                        divisions: 80,
                        enabled: widget.controller.canControl,
                        onChanged: (value) =>
                            setState(() => _minSavings = value),
                      ),
                      _SliderSetting(
                        label: 'Jobs per cycle',
                        valueLabel: '${_batchLimit.round()}',
                        value: _batchLimit,
                        min: 1,
                        max: 12,
                        divisions: 11,
                        enabled: widget.controller.canControl,
                        onChanged: (value) =>
                            setState(() => _batchLimit = value),
                      ),
                      _SliderSetting(
                        label: 'Maximum active jobs',
                        valueLabel: '${_maxActive.round()}',
                        value: _maxActive,
                        min: 1,
                        max: 20,
                        divisions: 19,
                        enabled: widget.controller.canControl,
                        onChanged: (value) =>
                            setState(() => _maxActive = value),
                      ),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          Expanded(
                            child: TextFormField(
                              initialValue: _start,
                              enabled: widget.controller.canControl,
                              decoration: const InputDecoration(
                                  labelText: 'Schedule starts',
                                  prefixIcon: Icon(Icons.schedule_rounded)),
                              onChanged: (value) => _start = value,
                            ),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: TextFormField(
                              initialValue: _end,
                              enabled: widget.controller.canControl,
                              decoration: const InputDecoration(
                                  labelText: 'Schedule ends',
                                  prefixIcon: Icon(Icons.schedule_rounded)),
                              onChanged: (value) => _end = value,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 16),
                      FilledButton.icon(
                        onPressed: widget.controller.canControl && !_saving
                            ? _save
                            : null,
                        icon: _saving
                            ? const SizedBox(
                                width: 18,
                                height: 18,
                                child:
                                    CircularProgressIndicator(strokeWidth: 2))
                            : const Icon(Icons.save_outlined),
                        label: const Text('Save automation policy'),
                      ),
                    ],
                  ),
                ),
                SectionHeader(
                    title: 'Readiness',
                    subtitle: ready
                        ? 'The safety checks are satisfied'
                        : 'Resolve these items in the web dashboard'),
                SurfaceCard(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: checks.isEmpty
                      ? const Padding(
                          padding: EdgeInsets.all(18),
                          child: Text('No readiness data is available.',
                              style: TextStyle(color: ByteSqueezeColors.muted)))
                      : Column(
                          children: checks.map((row) {
                            final check = asMap(row);
                            final ok =
                                check['ok'] == true || check['ready'] == true;
                            return ListTile(
                              leading: Icon(
                                  ok
                                      ? Icons.check_circle_rounded
                                      : Icons.warning_amber_rounded,
                                  color: ok
                                      ? ByteSqueezeColors.mint
                                      : ByteSqueezeColors.amber),
                              title: Text(
                                  '${check['label'] ?? check['name'] ?? 'Check'}'),
                              subtitle: Text(
                                  '${check['detail'] ?? check['message'] ?? ''}',
                                  style: const TextStyle(
                                      color: ByteSqueezeColors.muted)),
                            );
                          }).toList(),
                        ),
                ),
                const SectionHeader(
                    title: 'Smart Preset brain',
                    subtitle:
                        'Learned choices used by ByteSqueeze and Autopilot'),
                _SmartPresetCard(
                    controller: widget.controller,
                    profile: smartProfile,
                    learning: learning),
                const SectionHeader(
                    title: 'Latest decisions',
                    subtitle:
                        'Why media was selected, skipped, or left waiting'),
                if (decisions.isEmpty)
                  const SurfaceCard(
                      child: Text(
                          'Run an Autopilot cycle to generate explained decisions.',
                          style: TextStyle(color: ByteSqueezeColors.muted)))
                else
                  ...decisions.take(12).map((row) => Padding(
                        padding: const EdgeInsets.only(bottom: 9),
                        child: _DecisionCard(decision: asMap(row)),
                      )),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      await widget.controller.saveAutomation({
        'autopilot_enabled': _enabled,
        'autopilot_mode': _mode,
        'autopilot_include_movies': _movies,
        'autopilot_include_shows': _shows,
        'autopilot_min_size_gb': _minSize,
        'autopilot_min_savings_percent': _minSavings,
        'autopilot_batch_limit': _batchLimit.round(),
        'autopilot_max_active_jobs': _maxActive.round(),
        'autopilot_schedule_start': _start,
        'autopilot_schedule_end': _end,
        'autopilot_continuous_learning_enabled': _continuousLearning,
        'beta_auto_scan_enabled': _scanEnabled,
        'beta_auto_scan_file_stability_enabled': true,
        'beta_auto_scan_file_stability_minutes': _stabilityMinutes.round(),
      });
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Automation policy saved.')));
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$error')));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  void _applyProfile(String profile) {
    setState(() {
      _enabled = true;
      _scanEnabled = true;
      _movies = true;
      _shows = true;
      if (profile == 'safe') {
        _mode = 'observe';
        _minSize = 2;
        _minSavings = 15;
        _batchLimit = 2;
        _maxActive = 3;
        _stabilityMinutes = 20;
      } else if (profile == 'hands_off') {
        _mode = 'manage';
        _minSize = .5;
        _minSavings = 8;
        _batchLimit = 5;
        _maxActive = 8;
        _stabilityMinutes = 15;
      } else {
        _mode = 'observe';
        _minSize = 1;
        _minSavings = 10;
        _batchLimit = 3;
        _maxActive = 5;
        _stabilityMinutes = 10;
      }
    });
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(
          '${profile == 'safe' ? 'Safe starter' : profile == 'hands_off' ? 'Hands-off' : 'Balanced'} loaded. Review it, then save.'),
    ));
  }

  Future<void> _restartTour() async {
    try {
      if (widget.controller.canControl) {
        await widget.controller.setAutopilotTourCompleted(false);
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$error')));
      }
    }
    if (mounted) await _showTour();
  }

  Future<void> _showTour() async {
    final completed = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      backgroundColor: ByteSqueezeColors.navy,
      showDragHandle: true,
      builder: (context) => const _AutopilotTourSheet(),
    );
    if (completed == true && widget.controller.canControl) {
      try {
        await widget.controller.setAutopilotTourCompleted(true);
      } catch (error) {
        if (mounted) {
          ScaffoldMessenger.of(context)
              .showSnackBar(SnackBar(content: Text('$error')));
        }
      }
    }
  }

  Future<void> _showGuide() async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      backgroundColor: ByteSqueezeColors.navy,
      showDragHandle: true,
      builder: (context) => const _AutopilotGuideSheet(),
    );
  }

  Future<void> _run(Future<void> Function() action, {String? success}) async {
    try {
      await action();
      if (!mounted || success == null) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(success)));
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$error')));
    }
  }
}

class _CompletedFeedbackCard extends StatelessWidget {
  const _CompletedFeedbackCard(
      {required this.controller, required this.learning});

  final AppController controller;
  final Map<String, dynamic> learning;

  @override
  Widget build(BuildContext context) {
    final enabled = learning['enabled'] != false;
    final jobs = asList(learning['jobs']);
    final pending = (learning['pending'] as num?)?.toInt() ?? 0;
    return SurfaceCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              const Icon(Icons.rate_review_outlined,
                  color: ByteSqueezeColors.cyan),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('After-watch feedback',
                        style: Theme.of(context).textTheme.titleLarge),
                    const Text(
                        'Correct presets after watching the completed encode',
                        style: TextStyle(
                            color: ByteSqueezeColors.muted, fontSize: 12)),
                  ],
                ),
              ),
              StatusPill(
                  label: '$pending waiting',
                  color: pending > 0
                      ? ByteSqueezeColors.amber
                      : ByteSqueezeColors.mint),
            ],
          ),
          const SizedBox(height: 13),
          if (!enabled)
            const Text(
                'Continuous learning is off. Turn it on in Operating policy to review completed learned jobs.',
                style: TextStyle(color: ByteSqueezeColors.muted))
          else if (jobs.isEmpty)
            const Text(
                'Completed Autopilot and Smart Preset jobs will appear here after they finish.',
                style: TextStyle(color: ByteSqueezeColors.muted))
          else
            ...jobs.take(5).map((value) {
              final job = asMap(value);
              final needsFeedback = job['needs_feedback'] == true;
              return Padding(
                padding: const EdgeInsets.only(top: 8),
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    color: ByteSqueezeColors.raised,
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(color: ByteSqueezeColors.line),
                  ),
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text('${job['title'] ?? 'Completed encode'}',
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style:
                                const TextStyle(fontWeight: FontWeight.w800)),
                        const SizedBox(height: 3),
                        Text(
                            '${job['candidate_id'] ?? 'Smart preset'} - saved ${formatBytes(job['saved_bytes'])}',
                            style: const TextStyle(
                                color: ByteSqueezeColors.muted, fontSize: 12)),
                        const SizedBox(height: 10),
                        if (needsFeedback)
                          Row(
                            children: [
                              Expanded(
                                child: FilledButton.icon(
                                  onPressed: controller.canControl
                                      ? () => _submit(context, job,
                                          'approve', 'looks_good')
                                      : null,
                                  icon: const Icon(
                                      Icons.thumb_up_alt_outlined, size: 18),
                                  label: const Text('Looked good'),
                                ),
                              ),
                              const SizedBox(width: 8),
                              Expanded(
                                child: OutlinedButton.icon(
                                  onPressed: controller.canControl
                                      ? () => _reportProblem(context, job)
                                      : null,
                                  icon: const Icon(Icons.tune_rounded, size: 18),
                                  label: const Text('Problem'),
                                ),
                              ),
                            ],
                          )
                        else
                          Text(
                              'Feedback saved: ${asMap(job['feedback'])['verdict'] ?? 'done'}',
                              style: const TextStyle(
                                  color: ByteSqueezeColors.mint,
                                  fontWeight: FontWeight.w700)),
                      ],
                    ),
                  ),
                ),
              );
            }),
        ],
      ),
    );
  }

  Future<void> _reportProblem(
      BuildContext context, Map<String, dynamic> job) async {
    final reason = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const ListTile(
              title: Text('What was wrong after watching?',
                  style: TextStyle(fontWeight: FontWeight.w800)),
              subtitle: Text('This changes future choices for similar media.'),
            ),
            for (final choice in const [
              ('quality', Icons.high_quality_rounded, 'Picture quality'),
              ('playback', Icons.play_circle_outline, 'Playback or compatibility'),
              ('audio', Icons.volume_up_outlined, 'Audio choice'),
              ('subtitles', Icons.subtitles_outlined, 'Subtitle choice'),
              ('size', Icons.compress_rounded, 'File was too large'),
              ('other', Icons.more_horiz_rounded, 'Something else'),
            ])
              ListTile(
                leading: Icon(choice.$2),
                title: Text(choice.$3),
                onTap: () => Navigator.pop(sheetContext, choice.$1),
              ),
          ],
        ),
      ),
    );
    if (reason != null && context.mounted) {
      await _submit(context, job, 'reject', reason);
    }
  }

  Future<void> _submit(BuildContext context, Map<String, dynamic> job,
      String verdict, String reason) async {
    try {
      await controller.submitCompletedEncodeFeedback(
          '${job['id'] ?? ''}', verdict, reason);
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Feedback saved for future similar encodes.')));
    } catch (error) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$error')));
    }
  }
}

class _AutopilotTourSheet extends StatefulWidget {
  const _AutopilotTourSheet();

  @override
  State<_AutopilotTourSheet> createState() => _AutopilotTourSheetState();
}

class _AutopilotTourSheetState extends State<_AutopilotTourSheet> {
  int _step = 0;

  static const _steps = [
    (
      Icons.folder_copy_outlined,
      'Map only the folders you trust',
      'Set Movies and Shows folders on the web server. Autopilot never searches outside those mapped locations.'
    ),
    (
      Icons.visibility_outlined,
      'Start safely in Observe',
      'Observe scans and explains what it would select without adding anything to the queue.'
    ),
    (
      Icons.compare_rounded,
      'Teach with accurate previews',
      'Generate a real comparison below, inspect the original and proposal, then approve it or say what needs improvement. Two consistent reviews normally unlock learned automation.'
    ),
    (
      Icons.tune_rounded,
      'Choose clear guardrails',
      'Set the stable-file wait, minimum savings, schedule, batch size, and maximum active jobs before switching to Manage.'
    ),
    (
      Icons.rate_review_outlined,
      'Keep teaching after playback',
      'If a completed encode looks or sounds wrong later, report it here. Picture, playback, audio, subtitles, and size feedback all change future choices.'
    ),
  ];

  @override
  Widget build(BuildContext context) {
    final step = _steps[_step];
    final last = _step == _steps.length - 1;
    return FractionallySizedBox(
      heightFactor: .82,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(24, 8, 24, 24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                const Expanded(
                  child: Text('Autopilot guided setup',
                      style: TextStyle(
                          fontSize: 21, fontWeight: FontWeight.w900)),
                ),
                Text('${_step + 1}/${_steps.length}',
                    style: const TextStyle(color: ByteSqueezeColors.muted)),
              ],
            ),
            const SizedBox(height: 12),
            LinearProgressIndicator(value: (_step + 1) / _steps.length),
            Expanded(
              child: Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    DecoratedBox(
                      decoration: BoxDecoration(
                          color: ByteSqueezeColors.cyan.withValues(alpha: .12),
                          shape: BoxShape.circle),
                      child: Padding(
                        padding: const EdgeInsets.all(24),
                        child: Icon(step.$1,
                            size: 54, color: ByteSqueezeColors.cyan),
                      ),
                    ),
                    const SizedBox(height: 24),
                    Text(step.$2,
                        textAlign: TextAlign.center,
                        style: Theme.of(context).textTheme.headlineSmall),
                    const SizedBox(height: 12),
                    Text(step.$3,
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                            color: ByteSqueezeColors.muted,
                            fontSize: 15,
                            height: 1.45)),
                  ],
                ),
              ),
            ),
            Row(
              children: [
                if (_step > 0)
                  TextButton.icon(
                    onPressed: () => setState(() => _step--),
                    icon: const Icon(Icons.arrow_back_rounded),
                    label: const Text('Back'),
                  )
                else
                  const Spacer(),
                const Spacer(),
                FilledButton.icon(
                  onPressed: () {
                    if (last) {
                      Navigator.pop(context, true);
                    } else {
                      setState(() => _step++);
                    }
                  },
                  icon: Icon(last
                      ? Icons.check_circle_outline_rounded
                      : Icons.arrow_forward_rounded),
                  label: Text(last ? 'Start with Observe' : 'Next'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _AutopilotGuideSheet extends StatelessWidget {
  const _AutopilotGuideSheet();

  @override
  Widget build(BuildContext context) {
    const sections = [
      (
        '1. Set up',
        'Map Movies and Shows on the web, choose Safe starter or Balanced, keep Observe selected, enable drive watching, and save.'
      ),
      (
        '2. Train',
        'In Preview training, generate an accurate sample. Compare faces, motion, dark scenes, subtitles, and text edges. Approve good results or identify the problem.'
      ),
      (
        '3. Verify',
        'Run a decision cycle in Observe. Read the readiness checks and latest decisions until the selected and skipped work makes sense.'
      ),
      (
        '4. Automate',
        'Switch to Manage only after training is ready. Manage still obeys stable-file waits, schedule, savings, queue limits, output validation, and source protection.'
      ),
      (
        '5. Continue learning',
        'After watching completed learned encodes, use After-watch feedback. A quality problem favors a roomier preset; a size problem favors a smaller one; audio and subtitle reports influence track choices.'
      ),
      (
        'If something is unclear',
        'Stay in Observe, generate another preview from a different title, and check Readiness. Nothing is automatically queued while Observe is active.'
      ),
    ];
    return FractionallySizedBox(
      heightFactor: .9,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(22, 8, 22, 36),
        children: [
          Text('Autopilot guide',
              style: Theme.of(context).textTheme.headlineMedium),
          const SizedBox(height: 6),
          const Text('The complete phone workflow, from setup to feedback.',
              style: TextStyle(color: ByteSqueezeColors.muted)),
          const SizedBox(height: 18),
          ...sections.map((section) => Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: SurfaceCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(section.$1,
                          style: const TextStyle(fontWeight: FontWeight.w900)),
                      const SizedBox(height: 7),
                      Text(section.$2,
                          style: const TextStyle(
                              color: ByteSqueezeColors.muted, height: 1.4)),
                    ],
                  ),
                ),
              )),
        ],
      ),
    );
  }
}

class _AutopilotGuideCard extends StatelessWidget {
  const _AutopilotGuideCard({
    required this.onProfile,
    required this.enabled,
    required this.onTour,
    required this.onGuide,
  });

  final ValueChanged<String> onProfile;
  final bool enabled;
  final VoidCallback onTour;
  final VoidCallback onGuide;

  @override
  Widget build(BuildContext context) {
    const steps = [
      (
        '1',
        'Map folders',
        'Tell ByteSqueeze exactly where Movies and Shows live.'
      ),
      ('2', 'Observe', 'Run a cycle. Nothing is queued in Observe mode.'),
      (
        '3',
        'Teach',
        'Generate and review accurate comparisons in the training card below.'
      ),
      (
        '4',
        'Guardrails',
        'Set write safety, savings, schedule, and queue limits.'
      ),
      (
        '5',
        'Manage',
        'Allow bounded queueing only after the decisions look right.'
      ),
    ];
    return SurfaceCard(
      gradient: const LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [Color(0xFF13385A), Color(0xFF09182D)],
      ),
      borderColor: ByteSqueezeColors.cyan.withValues(alpha: .38),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              const Icon(Icons.route_rounded, color: ByteSqueezeColors.cyan),
              const SizedBox(width: 10),
              Expanded(
                child: Text('How Autopilot works',
                    style: Theme.of(context).textTheme.titleLarge),
              ),
              const StatusPill(label: '5 steps', color: ByteSqueezeColors.cyan),
            ],
          ),
          const SizedBox(height: 14),
          ...steps.map((step) => Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    CircleAvatar(
                      radius: 14,
                      backgroundColor:
                          ByteSqueezeColors.cyan.withValues(alpha: .16),
                      child: Text(step.$1,
                          style: const TextStyle(
                              color: ByteSqueezeColors.cyan,
                              fontSize: 12,
                              fontWeight: FontWeight.w800)),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: RichText(
                        text: TextSpan(
                          style: DefaultTextStyle.of(context).style,
                          children: [
                            TextSpan(
                                text: '${step.$2}  ',
                                style: const TextStyle(
                                    fontWeight: FontWeight.w800)),
                            TextSpan(
                                text: step.$3,
                                style: const TextStyle(
                                    color: ByteSqueezeColors.muted)),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              )),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              OutlinedButton.icon(
                onPressed: onTour,
                icon: const Icon(Icons.route_outlined),
                label: const Text('Restart guided tour'),
              ),
              TextButton.icon(
                onPressed: onGuide,
                icon: const Icon(Icons.menu_book_outlined),
                label: const Text('Read full guide'),
              ),
            ],
          ),
          const SizedBox(height: 10),
          const Divider(),
          const Text('Pick a starting policy',
              style: TextStyle(fontWeight: FontWeight.w800)),
          const SizedBox(height: 9),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              ActionChip(
                  avatar: const Icon(Icons.shield_outlined, size: 18),
                  label: const Text('Safe starter'),
                  onPressed: enabled ? () => onProfile('safe') : null),
              ActionChip(
                  avatar: const Icon(Icons.balance_rounded, size: 18),
                  label: const Text('Balanced'),
                  onPressed: enabled ? () => onProfile('balanced') : null),
              ActionChip(
                  avatar: const Icon(Icons.auto_awesome_rounded, size: 18),
                  label: const Text('Hands-off'),
                  onPressed: enabled ? () => onProfile('hands_off') : null),
            ],
          ),
          const SizedBox(height: 10),
          const Text(
            'Observe never queues. Manage still waits for complete files and keeps the existing output verification and source protection.',
            style: TextStyle(color: ByteSqueezeColors.muted, fontSize: 12),
          ),
        ],
      ),
    );
  }
}

class _AutopilotTrainingCard extends StatefulWidget {
  const _AutopilotTrainingCard({required this.controller});

  final AppController controller;

  @override
  State<_AutopilotTrainingCard> createState() =>
      _AutopilotTrainingCardState();
}

class _AutopilotTrainingCardState extends State<_AutopilotTrainingCard> {
  bool _working = false;

  @override
  Widget build(BuildContext context) {
    final review = widget.controller.autopilotReview;
    final preview = asMap(review['preview']);
    final result = asMap(preview['result']);
    final learning = asMap(review['learning']);
    final state = '${preview['state'] ?? 'idle'}';
    final encoding = const {
      'queued',
      'planning',
      'encoding',
      'framing',
      'muxing'
    }.contains(state);
    final ready = state == 'done' && result['ok'] == true;
    final reviewed = review['reviewed'] == true;
    final learningReady = learning['automation_ready'] == true;
    final progress =
        ((preview['progress'] as num?)?.toDouble() ?? 0).clamp(0, 100) / 100;

    return SurfaceCard(
      gradient: const LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [Color(0xFF143D67), Color(0xFF08182D)],
      ),
      borderColor: ByteSqueezeColors.cyan.withValues(alpha: .42),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              DecoratedBox(
                decoration: BoxDecoration(
                    color: ByteSqueezeColors.cyan.withValues(alpha: .13),
                    borderRadius: BorderRadius.circular(14)),
                child: const Padding(
                  padding: EdgeInsets.all(11),
                  child: Icon(Icons.compare_rounded,
                      color: ByteSqueezeColors.cyan),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Preview training',
                        style: Theme.of(context).textTheme.titleLarge),
                    Text(
                      learningReady
                          ? 'Learned automation is ready'
                          : '${learning['feedback_count'] ?? 0} reviewed · ${learning['reviews_needed'] ?? 0} minimum remaining',
                      style: const TextStyle(
                          color: ByteSqueezeColors.muted, fontSize: 12),
                    ),
                  ],
                ),
              ),
              StatusPill(
                label: learningReady ? 'Ready' : 'Learning',
                color: learningReady
                    ? ByteSqueezeColors.mint
                    : ByteSqueezeColors.cyan,
                icon: learningReady
                    ? Icons.verified_rounded
                    : Icons.school_outlined,
              ),
            ],
          ),
          const SizedBox(height: 15),
          Text(
            '${preview['message'] ?? learning['message'] ?? 'Generate a short, accurate sample from your library. Compare the original with the proposed encode, then tell ByteSqueeze what you think.'}',
            style: const TextStyle(color: ByteSqueezeColors.muted, height: 1.35),
          ),
          if (encoding) ...[
            const SizedBox(height: 14),
            LinearProgressIndicator(value: progress == 0 ? null : progress),
            const SizedBox(height: 7),
            Text('${(progress * 100).round()}% complete',
                style: const TextStyle(
                    color: ByteSqueezeColors.cyan, fontSize: 12)),
          ],
          if (ready) ...[
            const SizedBox(height: 16),
            Text('${review['title'] ?? 'Training sample'}',
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontWeight: FontWeight.w800)),
            const SizedBox(height: 4),
            Text(
                '${review['candidate_name'] ?? 'Smart Preset'} · original versus ByteSqueeze proposal',
                style: const TextStyle(
                    color: ByteSqueezeColors.muted, fontSize: 12)),
            const SizedBox(height: 12),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                    child: _PreviewFrame(
                        label: 'Original', base64Value: '${result['old_b64'] ?? ''}')),
                const SizedBox(width: 9),
                Expanded(
                    child: _PreviewFrame(
                        label: 'Proposal', base64Value: '${result['new_b64'] ?? ''}')),
              ],
            ),
            const SizedBox(height: 9),
            const Text(
              'Inspect faces, motion detail, dark scenes, subtitles, and text edges. The server encoded this exact sample with the proposed preset.',
              style: TextStyle(color: ByteSqueezeColors.muted, fontSize: 11.5),
            ),
          ],
          const SizedBox(height: 15),
          if (ready && !reviewed)
            Row(
              children: [
                Expanded(
                  child: FilledButton.icon(
                    onPressed: _working ? null : () => _submit('approve', 'looks_good'),
                    icon: const Icon(Icons.thumb_up_alt_outlined),
                    label: const Text('Looks good'),
                  ),
                ),
                const SizedBox(width: 9),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: _working ? null : _chooseRejection,
                    icon: const Icon(Icons.tune_rounded),
                    label: const Text('Needs changes'),
                  ),
                ),
              ],
            )
          else
            FilledButton.icon(
              onPressed: widget.controller.canControl && !_working && !encoding
                  ? () => _start(next: ready || reviewed)
                  : null,
              icon: _working || encoding
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.play_circle_outline_rounded),
              label: Text(ready || reviewed
                  ? 'Generate another sample'
                  : 'Generate accurate preview'),
            ),
          if (ready && !reviewed) ...[
            const SizedBox(height: 8),
            TextButton.icon(
              onPressed: _working ? null : () => _start(next: true),
              icon: const Icon(Icons.skip_next_rounded),
              label: const Text('Use a different library sample'),
            ),
          ],
        ],
      ),
    );
  }

  Future<void> _start({required bool next}) async {
    setState(() => _working = true);
    try {
      await widget.controller.startAutopilotReview(next: next);
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$error')));
      }
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  Future<void> _submit(String verdict, String reason) async {
    setState(() => _working = true);
    try {
      await widget.controller.submitAutopilotReview(verdict, reason);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(verdict == 'approve'
              ? 'Approved. Autopilot learned from this preview.'
              : 'Feedback saved. Future preset choices will adjust.')));
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$error')));
      }
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  Future<void> _chooseRejection() async {
    final reason = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const ListTile(
              title: Text('What should ByteSqueeze improve?',
                  style: TextStyle(fontWeight: FontWeight.w800)),
              subtitle: Text('This reason helps rank the next safe preset.'),
            ),
            for (final choice in const [
              ('quality', Icons.high_quality_rounded, 'Quality needs work'),
              ('size', Icons.compress_rounded, 'File should be smaller'),
              ('speed', Icons.speed_rounded, 'Encode should be faster'),
              ('compatibility', Icons.devices_rounded, 'Compatibility concern'),
              ('other', Icons.more_horiz_rounded, 'Something else'),
            ])
              ListTile(
                leading: Icon(choice.$2),
                title: Text(choice.$3),
                onTap: () => Navigator.pop(context, choice.$1),
              ),
          ],
        ),
      ),
    );
    if (reason != null) await _submit('reject', reason);
  }
}

class _PreviewFrame extends StatelessWidget {
  const _PreviewFrame({required this.label, required this.base64Value});

  final String label;
  final String base64Value;

  @override
  Widget build(BuildContext context) {
    Widget image;
    try {
      image = Image.memory(base64Decode(base64Value),
          fit: BoxFit.cover, gaplessPlayback: true);
    } catch (_) {
      image = const Center(
          child: Icon(Icons.broken_image_outlined,
              color: ByteSqueezeColors.muted));
    }
    return ClipRRect(
      borderRadius: BorderRadius.circular(13),
      child: DecoratedBox(
        decoration: const BoxDecoration(color: Colors.black),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            AspectRatio(aspectRatio: 16 / 9, child: image),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 7),
              child: Text(label,
                  style: const TextStyle(
                      color: ByteSqueezeColors.muted,
                      fontSize: 11,
                      fontWeight: FontWeight.w700)),
            ),
          ],
        ),
      ),
    );
  }
}

class _MiniMetric extends StatelessWidget {
  const _MiniMetric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Column(
        children: [
          Text(value, style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 3),
          Text(label,
              style: const TextStyle(
                  color: ByteSqueezeColors.muted, fontSize: 12)),
        ],
      ),
    );
  }
}

class _SliderSetting extends StatelessWidget {
  const _SliderSetting({
    required this.label,
    required this.valueLabel,
    required this.value,
    required this.min,
    required this.max,
    required this.divisions,
    required this.enabled,
    required this.onChanged,
  });

  final String label;
  final String valueLabel;
  final double value;
  final double min;
  final double max;
  final int divisions;
  final bool enabled;
  final ValueChanged<double> onChanged;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 9),
      child: Column(
        children: [
          Row(children: [
            Expanded(
                child: Text(label,
                    style: const TextStyle(fontWeight: FontWeight.w600))),
            Text(valueLabel,
                style: const TextStyle(
                    color: ByteSqueezeColors.cyan, fontWeight: FontWeight.w700))
          ]),
          Slider(
              value: value.clamp(min, max).toDouble(),
              min: min,
              max: max,
              divisions: divisions,
              onChanged: enabled ? onChanged : null),
        ],
      ),
    );
  }
}

class _SmartPresetCard extends StatefulWidget {
  const _SmartPresetCard(
      {required this.controller,
      required this.profile,
      required this.learning});

  final AppController controller;
  final Map<String, dynamic> profile;
  final Map<String, dynamic> learning;

  @override
  State<_SmartPresetCard> createState() => _SmartPresetCardState();
}

class _SmartPresetCardState extends State<_SmartPresetCard> {
  late String _strategy;
  late bool _automationEnabled;
  late bool _neverDownscale;
  late bool _keepBlackBars;
  late bool _keepAspectRatio;
  late bool _neverTranscodeAudio;
  late bool _keepAllAudioLanguages;
  late bool _keepAllSubtitleLanguages;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _strategy = '${widget.profile['audio_strategy'] ?? 'copy'}';
    _automationEnabled = widget.profile['automation_enabled'] == true;
    _neverDownscale = widget.profile['never_downscale'] != false;
    _keepBlackBars = widget.profile['keep_black_bars'] != false;
    _keepAspectRatio = widget.profile['keep_aspect_ratio'] != false;
    _neverTranscodeAudio = widget.profile['never_transcode_audio'] != false;
    _keepAllAudioLanguages =
        widget.profile['keep_all_audio_languages'] != false;
    _keepAllSubtitleLanguages =
        widget.profile['keep_all_subtitle_languages'] != false;
  }

  @override
  Widget build(BuildContext context) {
    final ready = widget.learning['automation_ready'] == true;
    return SurfaceCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Icon(ready ? Icons.psychology_alt_rounded : Icons.school_outlined,
                  color:
                      ready ? ByteSqueezeColors.mint : ByteSqueezeColors.cyan),
              const SizedBox(width: 11),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(ready ? 'Automatic selection ready' : 'Still learning',
                        style: const TextStyle(fontWeight: FontWeight.w700)),
                    Text(
                        '${widget.learning['feedback_count'] ?? 0} reviewed previews',
                        style: const TextStyle(
                            color: ByteSqueezeColors.muted, fontSize: 12)),
                  ],
                ),
              ),
              StatusPill(
                  label:
                      '${(((widget.learning['approval_probability'] as num?)?.toDouble() ?? 0) * 100).round()}% fit',
                  color:
                      ready ? ByteSqueezeColors.mint : ByteSqueezeColors.cyan),
            ],
          ),
          const SizedBox(height: 16),
          DropdownButtonFormField<String>(
            key: ValueKey('${_neverTranscodeAudio}_$_strategy'),
            initialValue: _neverTranscodeAudio ? 'copy' : _strategy,
            decoration: const InputDecoration(
                labelText: 'Audio handling when passthrough is off',
                prefixIcon: Icon(Icons.surround_sound_rounded)),
            items: const [
              DropdownMenuItem(
                  value: 'copy',
                  child: Text('Original passthrough · exact quality')),
              DropdownMenuItem(
                  value: 'eac3_surround',
                  child: Text('Smaller E-AC3 · 5.1 surround')),
            ],
            onChanged: widget.controller.canControl && !_neverTranscodeAudio
                ? (value) => setState(() => _strategy = value ?? 'copy')
                : null,
          ),
          const SizedBox(height: 14),
          const Text('Source protection',
              style: TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          const Text(
              'These hard rules also apply to full-season queues and cannot be bypassed by one-time fine tuning.',
              style: TextStyle(color: ByteSqueezeColors.muted, fontSize: 12.5)),
          SwitchListTile.adaptive(
            contentPadding: EdgeInsets.zero,
            value: _neverDownscale,
            onChanged: widget.controller.canControl
                ? (value) => setState(() => _neverDownscale = value)
                : null,
            title: const Text('Never downscale or resize'),
            subtitle: const Text('Keep the source width and height.'),
            secondary: const Icon(Icons.aspect_ratio_rounded),
          ),
          SwitchListTile.adaptive(
            contentPadding: EdgeInsets.zero,
            value: _keepBlackBars,
            onChanged: widget.controller.canControl
                ? (value) => setState(() => _keepBlackBars = value)
                : null,
            title: const Text('Keep black bars'),
            subtitle: const Text('Disable automatic picture cropping.'),
            secondary: const Icon(Icons.crop_free_rounded),
          ),
          SwitchListTile.adaptive(
            contentPadding: EdgeInsets.zero,
            value: _keepAspectRatio,
            onChanged: widget.controller.canControl
                ? (value) => setState(() => _keepAspectRatio = value)
                : null,
            title: const Text('Keep source aspect ratio'),
            subtitle: const Text('Do not reshape the source picture.'),
            secondary: const Icon(Icons.fit_screen_rounded),
          ),
          SwitchListTile.adaptive(
            contentPadding: EdgeInsets.zero,
            value: _neverTranscodeAudio,
            onChanged: widget.controller.canControl
                ? (value) => setState(() {
                      _neverTranscodeAudio = value;
                      if (value) _strategy = 'copy';
                    })
                : null,
            title: const Text('Never transcode audio'),
            subtitle: const Text(
                'Passthrough source audio; incompatible containers fail instead of silently converting.'),
            secondary: const Icon(Icons.surround_sound_rounded),
          ),
          SwitchListTile.adaptive(
            contentPadding: EdgeInsets.zero,
            value: _keepAllAudioLanguages,
            onChanged: widget.controller.canControl
                ? (value) => setState(() => _keepAllAudioLanguages = value)
                : null,
            title: const Text('Keep every audio language'),
            subtitle: const Text('Select every source audio track.'),
            secondary: const Icon(Icons.record_voice_over_rounded),
          ),
          SwitchListTile.adaptive(
            contentPadding: EdgeInsets.zero,
            value: _keepAllSubtitleLanguages,
            onChanged: widget.controller.canControl
                ? (value) => setState(() => _keepAllSubtitleLanguages = value)
                : null,
            title: const Text('Keep every subtitle language'),
            subtitle: const Text('Keep all subtitles without burn-in.'),
            secondary: const Icon(Icons.subtitles_rounded),
          ),
          SwitchListTile.adaptive(
            contentPadding: EdgeInsets.zero,
            value: _automationEnabled,
            onChanged: widget.controller.canControl
                ? (value) => setState(() => _automationEnabled = value)
                : null,
            title: const Text('Use learned presets automatically'),
            subtitle: const Text(
                'Unlocks only after enough accurate previews are approved.'),
            secondary: const Icon(Icons.psychology_alt_rounded),
          ),
          const SizedBox(height: 14),
          OutlinedButton.icon(
            onPressed: widget.controller.canControl && !_saving ? _save : null,
            icon: _saving
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.save_outlined),
            label: const Text('Save Smart Preset protections'),
          ),
        ],
      ),
    );
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      await widget.controller
          .saveSmartProfile({
        ...widget.profile,
        'audio_strategy': _strategy,
        'never_downscale': _neverDownscale,
        'keep_black_bars': _keepBlackBars,
        'keep_aspect_ratio': _keepAspectRatio,
        'never_transcode_audio': _neverTranscodeAudio,
        'keep_all_audio_languages': _keepAllAudioLanguages,
        'keep_all_subtitle_languages': _keepAllSubtitleLanguages,
        'preserve_audio': _neverTranscodeAudio,
        'preserve_subtitles': _keepAllSubtitleLanguages,
        'automation_enabled': _automationEnabled,
      });
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$error')));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }
}

class _DecisionCard extends StatelessWidget {
  const _DecisionCard({required this.decision});

  final Map<String, dynamic> decision;

  @override
  Widget build(BuildContext context) {
    final type = '${decision['decision'] ?? 'wait'}'.toLowerCase();
    final color = type == 'eligible' || type == 'queue'
        ? ByteSqueezeColors.mint
        : (type == 'skip' ? ByteSqueezeColors.danger : ByteSqueezeColors.amber);
    return SurfaceCard(
      padding: const EdgeInsets.all(15),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
              type == 'skip'
                  ? Icons.block_rounded
                  : (type == 'wait'
                      ? Icons.schedule_rounded
                      : Icons.check_circle_outline_rounded),
              color: color),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${decision['title'] ?? fileName(decision['path'])}',
                    style: const TextStyle(fontWeight: FontWeight.w700)),
                const SizedBox(height: 4),
                Text('${decision['reason'] ?? 'No reason was recorded.'}',
                    style: const TextStyle(
                        color: ByteSqueezeColors.muted, fontSize: 12.5)),
              ],
            ),
          ),
          const SizedBox(width: 8),
          StatusPill(label: type, color: color),
        ],
      ),
    );
  }
}
