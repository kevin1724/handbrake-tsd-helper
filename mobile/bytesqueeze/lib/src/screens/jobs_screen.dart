import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../theme.dart';
import '../widgets/common.dart';

class JobsScreen extends StatefulWidget {
  const JobsScreen({super.key, required this.controller});

  final AppController controller;

  @override
  State<JobsScreen> createState() => _JobsScreenState();
}

class _JobsScreenState extends State<JobsScreen> {
  bool _history = false;
  String _filter = 'all';

  @override
  Widget build(BuildContext context) {
    final allJobs = asList(widget.controller.jobs['jobs']).map(asMap).toList();
    const activeStates = {'running', 'queued', 'waiting_to_upload'};
    final rows = allJobs.where((job) {
      final status = '${job['status'] ?? ''}'.toLowerCase();
      final inGroup = _history
          ? !activeStates.contains(status)
          : activeStates.contains(status);
      return inGroup && (_filter == 'all' || status == _filter);
    }).toList();
    final paused = widget.controller.jobs['paused'] == true;
    final summary = asMap(widget.controller.jobs['summary']);

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
                          Text('Jobs',
                              style: Theme.of(context).textTheme.headlineLarge),
                          const SizedBox(height: 4),
                          Text(
                            '${summary['running'] ?? 0} running · ${summary['queued'] ?? 0} queued · ${summary['done'] ?? 0} completed',
                            style:
                                const TextStyle(color: ByteSqueezeColors.muted),
                          ),
                        ],
                      ),
                    ),
                    FilledButton.tonalIcon(
                      onPressed: widget.controller.canControl
                          ? () => _run(
                              () => widget.controller.setQueuePaused(!paused))
                          : null,
                      icon: Icon(paused
                          ? Icons.play_arrow_rounded
                          : Icons.pause_rounded),
                      label: Text(paused ? 'Resume' : 'Pause'),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                SegmentedButton<bool>(
                  segments: const [
                    ButtonSegment(
                        value: false,
                        label: Text('Active'),
                        icon: Icon(Icons.motion_photos_on_rounded)),
                    ButtonSegment(
                        value: true,
                        label: Text('History'),
                        icon: Icon(Icons.history_rounded)),
                  ],
                  selected: {_history},
                  onSelectionChanged: (value) => setState(() {
                    _history = value.first;
                    _filter = 'all';
                  }),
                  showSelectedIcon: false,
                  style: ButtonStyle(
                      shape: WidgetStatePropertyAll(RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(14)))),
                ),
                const SizedBox(height: 12),
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: (_history
                            ? const ['all', 'done', 'error', 'canceled']
                            : const ['all', 'running', 'queued'])
                        .map((value) => Padding(
                              padding: const EdgeInsets.only(right: 8),
                              child: ChoiceChip(
                                selected: _filter == value,
                                onSelected: (_) =>
                                    setState(() => _filter = value),
                                label: Text(value == 'all'
                                    ? 'All'
                                    : '${value[0].toUpperCase()}${value.substring(1)}'),
                              ),
                            ))
                        .toList(),
                  ),
                ),
                if (_history && rows.isNotEmpty)
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton.icon(
                      onPressed: widget.controller.canControl
                          ? () => _confirmClear('finished')
                          : null,
                      icon: const Icon(Icons.delete_sweep_outlined),
                      label: const Text('Clear finished history'),
                    ),
                  )
                else
                  const SizedBox(height: 8),
                if (paused && !_history)
                  const Padding(
                    padding: EdgeInsets.only(bottom: 12),
                    child: SurfaceCard(
                      borderColor: ByteSqueezeColors.amber,
                      child: Row(
                        children: [
                          Icon(Icons.pause_circle_outline_rounded,
                              color: ByteSqueezeColors.amber),
                          SizedBox(width: 12),
                          Expanded(
                              child: Text(
                                  'The queue is paused. Running work may finish, but new jobs will not start.')),
                        ],
                      ),
                    ),
                  ),
                if (rows.isEmpty)
                  EmptyState(
                    icon: _history
                        ? Icons.history_toggle_off_rounded
                        : Icons.check_circle_outline_rounded,
                    title: _history ? 'No job history here' : 'No active jobs',
                    message: _history
                        ? 'Completed, failed, and canceled jobs appear here.'
                        : 'Queue media from Library or let Autopilot choose eligible work.',
                  )
                else
                  ...rows.map((job) => Padding(
                        padding: const EdgeInsets.only(bottom: 11),
                        child: _JobCard(
                            controller: widget.controller, job: job, run: _run),
                      )),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _confirmClear(String target) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Clear finished jobs?'),
        content: const Text(
            'This removes finished job rows and their logs from the TSD dashboard. Media files are not deleted.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Clear')),
        ],
      ),
    );
    if (confirmed == true) {
      await _run(() => widget.controller.clearJobs(target));
    }
  }

  Future<void> _run(Future<void> Function() action) async {
    try {
      await action();
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$error')));
    }
  }
}

class _JobCard extends StatelessWidget {
  const _JobCard(
      {required this.controller, required this.job, required this.run});

  final AppController controller;
  final Map<String, dynamic> job;
  final Future<void> Function(Future<void> Function()) run;

  @override
  Widget build(BuildContext context) {
    final status = '${job['status'] ?? 'unknown'}'.toLowerCase();
    final color = statusColor(status);
    final progress =
        ((job['progress'] as num?)?.toDouble() ?? 0).clamp(0, 100).toDouble();
    final canMove = status == 'queued' && controller.canControl;
    final canCancel =
        {'running', 'queued', 'waiting_to_upload'}.contains(status) &&
            controller.canControl;
    return SurfaceCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              DecoratedBox(
                decoration: BoxDecoration(
                    color: color.withValues(alpha: .12),
                    borderRadius: BorderRadius.circular(13)),
                child: Padding(
                  padding: const EdgeInsets.all(11),
                  child: Icon(
                      status == 'done'
                          ? Icons.check_rounded
                          : Icons.movie_filter_rounded,
                      color: color),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(fileName(job['src']),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 5),
                    Text(
                      '${job['encoder'] ?? job['encode_method'] ?? job['preset'] ?? 'Automatic'} · ${job['preset'] ?? 'auto'}',
                      style: const TextStyle(
                          color: ByteSqueezeColors.muted, fontSize: 12),
                    ),
                  ],
                ),
              ),
              PopupMenuButton<String>(
                enabled: controller.canControl,
                onSelected: (action) =>
                    run(() => controller.jobAction('${job['id']}', action)),
                itemBuilder: (context) => [
                  if (canMove) ...const [
                    PopupMenuItem(
                        value: 'top',
                        child: ListTile(
                            leading: Icon(Icons.vertical_align_top_rounded),
                            title: Text('Move to top'))),
                    PopupMenuItem(
                        value: 'up',
                        child: ListTile(
                            leading: Icon(Icons.keyboard_arrow_up_rounded),
                            title: Text('Move up'))),
                    PopupMenuItem(
                        value: 'down',
                        child: ListTile(
                            leading: Icon(Icons.keyboard_arrow_down_rounded),
                            title: Text('Move down'))),
                    PopupMenuItem(
                        value: 'bottom',
                        child: ListTile(
                            leading: Icon(Icons.vertical_align_bottom_rounded),
                            title: Text('Move to bottom'))),
                  ],
                  if (canCancel)
                    const PopupMenuItem(
                        value: 'cancel',
                        child: ListTile(
                            leading: Icon(Icons.cancel_outlined,
                                color: ByteSqueezeColors.danger),
                            title: Text('Cancel job'))),
                ],
              ),
            ],
          ),
          const SizedBox(height: 13),
          Row(
            children: [
              StatusPill(label: status.replaceAll('_', ' '), color: color),
              const Spacer(),
              if (status == 'running')
                Text(
                    '${progress.toStringAsFixed(0)}% · ${formatDuration(job['eta_seconds'])} left',
                    style: const TextStyle(
                        color: ByteSqueezeColors.muted, fontSize: 12)),
              if (status == 'done' && job['saved_bytes'] != null)
                Text('${formatBytes(job['saved_bytes'])} saved',
                    style: const TextStyle(
                        color: ByteSqueezeColors.mint, fontSize: 12)),
            ],
          ),
          if (status == 'running') ...[
            const SizedBox(height: 11),
            ClipRRect(
                borderRadius: BorderRadius.circular(999),
                child: LinearProgressIndicator(
                    value: progress / 100, minHeight: 8)),
          ],
          if ('${job['cancel_reason'] ?? ''}'.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text('${job['cancel_reason']}',
                style: const TextStyle(
                    color: ByteSqueezeColors.danger, fontSize: 12)),
          ],
        ],
      ),
    );
  }
}
