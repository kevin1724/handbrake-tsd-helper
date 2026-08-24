import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../theme.dart';
import '../widgets/common.dart';

class DashboardScreen extends StatelessWidget {
  const DashboardScreen({super.key, required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final queue = asMap(controller.dashboard['queue']);
    final summary = asMap(queue['summary']);
    final library = asMap(controller.dashboard['library']);
    final nodes = asMap(controller.dashboard['nodes']);
    final storage = asMap(controller.dashboard['storage']);
    final activeJobs = asList(controller.dashboard['active_jobs']);
    final events = asList(controller.dashboard['events']);
    final automationWrap = asMap(controller.dashboard['automation']);
    final autopilot = asMap(automationWrap['autopilot']);
    final paused = queue['paused'] == true;
    final savedBytes = storage['saved_bytes'] ?? summary['saved_bytes'] ?? 0;
    final runningJobs = activeJobs
        .map(asMap)
        .where((job) => '${job['status'] ?? ''}'.toLowerCase() == 'running')
        .toList();

    return RefreshIndicator(
      onRefresh: controller.refreshAll,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        children: [
          PageInsets(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _Hero(
                    controller: controller,
                    paused: paused,
                    summary: summary,
                    autopilot: autopilot),
                const SizedBox(height: 18),
                LayoutBuilder(
                  builder: (context, constraints) {
                    final columns = constraints.maxWidth >= 950
                        ? 4
                        : (constraints.maxWidth >= 520 ? 2 : 2);
                    final ratio = constraints.maxWidth < 420 ? 1.05 : 1.35;
                    return GridView.count(
                      crossAxisCount: columns,
                      shrinkWrap: true,
                      physics: const NeverScrollableScrollPhysics(),
                      mainAxisSpacing: 12,
                      crossAxisSpacing: 12,
                      childAspectRatio: ratio,
                      children: [
                        MetricCard(
                          label: 'Active jobs',
                          value: "${summaryCount(summary, 'running')} running",
                          detail: "${summaryCount(summary, 'queued')} waiting",
                          icon: Icons.motion_photos_on_rounded,
                          color: ByteSqueezeColors.cyan,
                        ),
                        MetricCard(
                          label: 'Media library',
                          value:
                              '${(library['movies'] as num?)?.toInt() ?? 0} movies',
                          detail:
                              '${(library['shows'] as num?)?.toInt() ?? 0} shows',
                          icon: Icons.video_library_rounded,
                          color: ByteSqueezeColors.blue,
                        ),
                        MetricCard(
                          label: 'Storage reclaimed',
                          value: formatBytes(savedBytes),
                          detail:
                              '${(storage['count'] as num?)?.toInt() ?? 0} completed encodes',
                          icon: Icons.savings_outlined,
                          color: ByteSqueezeColors.mint,
                        ),
                        MetricCard(
                          label: 'Encoding nodes',
                          value:
                              '${(nodes['online'] as num?)?.toInt() ?? 0} online',
                          detail:
                              '${(nodes['paired'] as num?)?.toInt() ?? 0} linked workers',
                          icon: Icons.hub_rounded,
                          color: ByteSqueezeColors.amber,
                        ),
                      ],
                    );
                  },
                ),
                SectionHeader(
                  title: 'Running now',
                  subtitle: runningJobs.isEmpty
                      ? 'All encoders are available'
                      : 'Live work from every controller and worker',
                  trailing: TextButton(
                      onPressed: () => controller.selectTab(2),
                      child: const Text('View jobs')),
                ),
                if (runningJobs.isEmpty)
                  const SurfaceCard(
                    child: Row(
                      children: [
                        Icon(Icons.check_circle_outline_rounded,
                            color: ByteSqueezeColors.mint),
                        SizedBox(width: 12),
                        Expanded(
                            child: Text(
                                'Nothing is encoding right now. Autopilot will add eligible media when allowed.')),
                      ],
                    ),
                  )
                else
                  ...runningJobs.take(4).map((job) => Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: _ActiveJobCard(job: job),
                      )),
                if (controller.showSecondaryUi) ...[
                  const SectionHeader(
                      title: 'Quick controls',
                      subtitle: 'Safe remote actions; encoding remains on TSD'),
                  Wrap(
                    spacing: 10,
                    runSpacing: 10,
                    children: [
                      FilledButton.tonalIcon(
                        onPressed: controller.canControl
                            ? () => _run(context,
                                () => controller.setQueuePaused(!paused))
                            : null,
                        icon: Icon(paused
                            ? Icons.play_arrow_rounded
                            : Icons.pause_rounded),
                        label: Text(paused ? 'Resume queue' : 'Pause queue'),
                      ),
                      FilledButton.tonalIcon(
                        onPressed: () => controller.selectTab(1),
                        icon: const Icon(Icons.movie_filter_outlined),
                        label: const Text('Browse library'),
                      ),
                      FilledButton.tonalIcon(
                        onPressed: () => controller.selectTab(3),
                        icon: const Icon(Icons.auto_awesome_rounded),
                        label: const Text('Open Autopilot'),
                      ),
                    ],
                  ),
                ],
                if (controller.statsForNerds) ...[
                  SectionHeader(
                    title: 'Recent activity',
                    subtitle: 'The latest server decisions and outcomes',
                    trailing: TextButton(
                        onPressed: () => controller.selectTab(4),
                        child: const Text('All events')),
                  ),
                  SurfaceCard(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: events.isEmpty
                        ? const Padding(
                            padding: EdgeInsets.all(18),
                            child: Text('No events have been recorded yet.',
                                style: TextStyle(
                                    color: ByteSqueezeColors.muted)))
                        : Column(
                            children: events.take(5).map((row) {
                            final event = asMap(row);
                            final level = '${event['level'] ?? 'info'}';
                            final color = level == 'error'
                                ? ByteSqueezeColors.danger
                                : (level == 'warn'
                                    ? ByteSqueezeColors.amber
                                    : ByteSqueezeColors.cyan);
                            return ListTile(
                              leading: DecoratedBox(
                                decoration: BoxDecoration(
                                    color: color.withValues(alpha: .12),
                                    shape: BoxShape.circle),
                                child: Padding(
                                    padding: const EdgeInsets.all(9),
                                    child: Icon(Icons.bolt_rounded,
                                        size: 18, color: color)),
                              ),
                              title: Text(
                                  '${event['message'] ?? event['type'] ?? 'Server event'}',
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis),
                              subtitle: Text(relativeTime(event['ts']),
                                  style: const TextStyle(
                                      color: ByteSqueezeColors.muted)),
                            );
                            }).toList(),
                          ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _run(
      BuildContext context, Future<void> Function() action) async {
    try {
      await action();
    } catch (error) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$error')));
    }
  }
}

class _Hero extends StatelessWidget {
  const _Hero(
      {required this.controller,
      required this.paused,
      required this.summary,
      required this.autopilot});

  final AppController controller;
  final bool paused;
  final Map<String, dynamic> summary;
  final Map<String, dynamic> autopilot;

  @override
  Widget build(BuildContext context) {
    final running = summaryCount(summary, 'running');
    final queued = summaryCount(summary, 'queued');
    final hardwareLimit =
        (summary['hardware_transcode_concurrency'] as num?)?.toInt() ?? 1;
    final autoEnabled = autopilot['enabled'] == true;
    return SurfaceCard(
      padding: const EdgeInsets.all(22),
      gradient: const LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [Color(0xFF123C78), Color(0xFF0D244A), Color(0xFF08162E)],
      ),
      borderColor: const Color(0xFF245A99),
      child: Stack(
        children: [
          Positioned(
            right: -48,
            top: -72,
            child: Container(
              width: 210,
              height: 210,
              decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: ByteSqueezeColors.cyan.withValues(alpha: .08)),
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Operations overview',
                            style: Theme.of(context)
                                .textTheme
                                .titleMedium
                                ?.copyWith(color: ByteSqueezeColors.cyan)),
                        const SizedBox(height: 5),
                        Text(
                            paused
                                ? 'Your media pipeline is paused.'
                                : 'Media operations are ready.',
                            style: Theme.of(context).textTheme.headlineMedium),
                      ],
                    ),
                  ),
                  Hero(
                    tag: 'bytesqueeze-icon',
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(18),
                      child: Image.asset('assets/branding/bytesqueeze_icon.png',
                          width: 70, height: 70),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 18),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  StatusPill(
                    label: paused
                        ? 'Queue paused'
                        : '$running encoding · $queued queued',
                    color: paused
                        ? ByteSqueezeColors.amber
                        : ByteSqueezeColors.mint,
                    icon: paused
                        ? Icons.pause_circle_outline_rounded
                        : Icons.play_circle_outline_rounded,
                  ),
                  if (controller.statsForNerds)
                    StatusPill(
                      label:
                          '$hardwareLimit GPU slot${hardwareLimit == 1 ? '' : 's'}',
                      color: ByteSqueezeColors.blue,
                      icon: Icons.developer_board_rounded,
                    ),
                  StatusPill(
                    label: autoEnabled
                        ? 'Autopilot ${autopilot['mode'] ?? 'observe'}'
                        : 'Autopilot off',
                    color: autoEnabled
                        ? ByteSqueezeColors.cyan
                        : ByteSqueezeColors.muted,
                    icon: Icons.auto_awesome_rounded,
                  ),
                  if (controller.statsForNerds)
                    StatusPill(
                        label: controller.serverLabel,
                        color: ByteSqueezeColors.blue,
                        icon: Icons.dns_outlined),
                ],
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _ActiveJobCard extends StatelessWidget {
  const _ActiveJobCard({required this.job});

  final Map<String, dynamic> job;

  @override
  Widget build(BuildContext context) {
    final progress =
        ((job['progress'] as num?)?.toDouble() ?? 0).clamp(0, 100).toDouble();
    final status = '${job['status'] ?? 'queued'}';
    final color = statusColor(status);
    return SurfaceCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              DecoratedBox(
                decoration: BoxDecoration(
                    color: color.withValues(alpha: .12),
                    borderRadius: BorderRadius.circular(12)),
                child: Padding(
                    padding: const EdgeInsets.all(10),
                    child: Icon(Icons.movie_filter_rounded, color: color)),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(fileName(job['src']),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 4),
                    Text(
                        '${job['encoder'] ?? job['preset'] ?? 'Smart Preset'} · ${formatDuration(job['eta_seconds'])} remaining',
                        style: const TextStyle(
                            color: ByteSqueezeColors.muted, fontSize: 12)),
                  ],
                ),
              ),
              StatusPill(label: status.replaceAll('_', ' '), color: color),
            ],
          ),
          const SizedBox(height: 14),
          ClipRRect(
              borderRadius: BorderRadius.circular(999),
              child: LinearProgressIndicator(
                  value: status == 'running' ? progress / 100 : 0,
                  minHeight: 7)),
          const SizedBox(height: 7),
          Align(
              alignment: Alignment.centerRight,
              child: Text('${progress.toStringAsFixed(0)}%',
                  style: const TextStyle(
                      color: ByteSqueezeColors.muted, fontSize: 12))),
        ],
      ),
    );
  }
}
