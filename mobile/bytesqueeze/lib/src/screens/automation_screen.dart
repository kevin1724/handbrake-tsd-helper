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
  bool _saving = false;

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
    _hydrated = true;
  }

  @override
  Widget build(BuildContext context) {
    if (!_hydrated) _hydrate();
    final status = asMap(widget.controller.automation['status']);
    final autopilot = asMap(status['autopilot']);
    final readiness = asMap(status['readiness']);
    final checks = asList(readiness['checks']);
    final decisions = asList(autopilot['decisions']);
    final smartProfile = asMap(widget.controller.smartPresets['profile']);
    final learning = asMap(widget.controller.smartPresets['learning']);
    final ready = readiness['ready'] == true;

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
                          Text('Automation',
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
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _strategy = '${widget.profile['audio_strategy'] ?? 'copy'}';
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
            initialValue: _strategy,
            decoration: const InputDecoration(
                labelText: 'English + Spanish audio handling',
                prefixIcon: Icon(Icons.surround_sound_rounded)),
            items: const [
              DropdownMenuItem(
                  value: 'copy',
                  child: Text('Original passthrough · exact quality')),
              DropdownMenuItem(
                  value: 'eac3_surround',
                  child: Text('Smaller E-AC3 · 5.1 surround')),
            ],
            onChanged: widget.controller.canControl
                ? (value) => setState(() => _strategy = value ?? 'copy')
                : null,
          ),
          const SizedBox(height: 9),
          const Text(
              'All matching English and Spanish audio and subtitle tracks stay selected.',
              style: TextStyle(color: ByteSqueezeColors.muted, fontSize: 12.5)),
          const SizedBox(height: 14),
          OutlinedButton.icon(
            onPressed: widget.controller.canControl && !_saving ? _save : null,
            icon: _saving
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.save_outlined),
            label: const Text('Save Smart Preset audio choice'),
          ),
        ],
      ),
    );
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      await widget.controller
          .saveSmartProfile({...widget.profile, 'audio_strategy': _strategy});
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
