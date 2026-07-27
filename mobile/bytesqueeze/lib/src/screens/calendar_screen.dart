import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../theme.dart';
import '../widgets/common.dart';

class CalendarScreen extends StatefulWidget {
  const CalendarScreen({super.key, required this.controller});

  final AppController controller;

  @override
  State<CalendarScreen> createState() => _CalendarScreenState();
}

class _CalendarScreenState extends State<CalendarScreen> {
  bool _trackedOnly = false;

  @override
  Widget build(BuildContext context) {
    final allDays = asList(widget.controller.calendar['days']).map(asMap);
    final days = allDays
        .map((day) {
          final episodes = asList(day['episodes'])
              .map(asMap)
              .where((episode) => !_trackedOnly || episode['tracked'] == true)
              .toList();
          return {...day, 'episodes': episodes};
        })
        .where((day) => asList(day['episodes']).isNotEmpty)
        .toList();
    final count = days.fold<int>(
        0, (total, day) => total + asList(day['episodes']).length);

    return RefreshIndicator(
      onRefresh: widget.controller.refreshAll,
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverToBoxAdapter(
            child: PageInsets(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('NEXT UP',
                                style: TextStyle(
                                    color: ByteSqueezeColors.cyan,
                                    fontSize: 11,
                                    fontWeight: FontWeight.w800,
                                    letterSpacing: 1.6)),
                            const SizedBox(height: 5),
                            Text('Release calendar',
                                style:
                                    Theme.of(context).textTheme.headlineLarge),
                            const SizedBox(height: 4),
                            Text(
                                '$count upcoming episodes known to your server',
                                style: const TextStyle(
                                    color: ByteSqueezeColors.muted)),
                          ],
                        ),
                      ),
                      IconButton.filledTonal(
                        tooltip: 'Refresh catalog',
                        onPressed: widget.controller.busy
                            ? null
                            : widget.controller.refreshAll,
                        icon: const Icon(Icons.sync_rounded),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  SegmentedButton<bool>(
                    segments: const [
                      ButtonSegment(
                          value: false,
                          icon: Icon(Icons.calendar_month_outlined),
                          label: Text('All shows')),
                      ButtonSegment(
                          value: true,
                          icon: Icon(Icons.notifications_active_outlined),
                          label: Text('Tracked')),
                    ],
                    selected: {_trackedOnly},
                    showSelectedIcon: false,
                    onSelectionChanged: (values) =>
                        setState(() => _trackedOnly = values.first),
                  ),
                  const SizedBox(height: 12),
                  SurfaceCard(
                    padding: const EdgeInsets.all(14),
                    borderColor: ByteSqueezeColors.cyan.withValues(alpha: .35),
                    child: const Row(
                      children: [
                        Icon(Icons.download_done_rounded,
                            color: ByteSqueezeColors.mint),
                        SizedBox(width: 12),
                        Expanded(
                          child: Text(
                            'The calendar predicts release dates. ByteSqueeze waits until the actual file appears on a mapped drive and stops changing before it can auto-queue it.',
                            style: TextStyle(fontSize: 12.5),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),
                ],
              ),
            ),
          ),
          if (days.isEmpty)
            const SliverToBoxAdapter(
              child: PageInsets(
                child: EmptyState(
                  icon: Icons.event_busy_outlined,
                  title: 'Nothing scheduled yet',
                  message:
                      'Track a show and refresh the Library. Release dates will appear here when TVmaze has them.',
                ),
              ),
            )
          else
            SliverList.builder(
              itemCount: days.length,
              itemBuilder: (context, index) {
                final day = days[index];
                return PageInsets(
                  child: _ReleaseDay(
                    date: '${day['date'] ?? ''}',
                    episodes: asList(day['episodes']).map(asMap).toList(),
                  ),
                );
              },
            ),
          const SliverToBoxAdapter(
            child: Padding(
              padding: EdgeInsets.fromLTRB(24, 8, 24, 118),
              child: Text(
                'TV data by TVmaze · CC BY-SA',
                textAlign: TextAlign.center,
                style:
                    TextStyle(color: ByteSqueezeColors.muted, fontSize: 11.5),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ReleaseDay extends StatelessWidget {
  const _ReleaseDay({required this.date, required this.episodes});

  final String date;
  final List<Map<String, dynamic>> episodes;

  @override
  Widget build(BuildContext context) {
    final parsed = DateTime.tryParse(date);
    final today = DateTime.now();
    final isToday = parsed != null &&
        parsed.year == today.year &&
        parsed.month == today.month &&
        parsed.day == today.day;
    return Padding(
      padding: const EdgeInsets.only(bottom: 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Text(isToday ? 'TODAY' : _dateLabel(parsed, date),
                  style: TextStyle(
                      color: isToday
                          ? ByteSqueezeColors.cyan
                          : ByteSqueezeColors.ink,
                      fontSize: 13,
                      fontWeight: FontWeight.w800,
                      letterSpacing: .8)),
              const SizedBox(width: 9),
              const Expanded(child: Divider(color: ByteSqueezeColors.line)),
              const SizedBox(width: 9),
              Text('${episodes.length}',
                  style: const TextStyle(color: ByteSqueezeColors.muted)),
            ],
          ),
          const SizedBox(height: 10),
          ...episodes.map(_EpisodeCard.new),
        ],
      ),
    );
  }

  static String _dateLabel(DateTime? date, String fallback) {
    if (date == null) return fallback;
    const months = [
      'Jan',
      'Feb',
      'Mar',
      'Apr',
      'May',
      'Jun',
      'Jul',
      'Aug',
      'Sep',
      'Oct',
      'Nov',
      'Dec'
    ];
    const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    return '${days[date.weekday - 1]}, ${months[date.month - 1]} ${date.day}';
  }
}

class _EpisodeCard extends StatelessWidget {
  const _EpisodeCard(this.episode);

  final Map<String, dynamic> episode;

  @override
  Widget build(BuildContext context) {
    final season = (episode['season'] as num?)?.toInt() ?? 0;
    final number = (episode['episode'] as num?)?.toInt() ?? 0;
    final art = {
      'title': episode['show_title'],
      'poster_url': episode['poster_url'],
    };
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: SurfaceCard(
        padding: const EdgeInsets.all(11),
        child: Row(
          children: [
            SizedBox(
              width: 64,
              height: 86,
              child: PosterArt(item: art, borderRadius: 12),
            ),
            const SizedBox(width: 13),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                            '${episode['show_title'] ?? 'Unknown show'}',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style:
                                const TextStyle(fontWeight: FontWeight.w800)),
                      ),
                      if (episode['tracked'] == true)
                        const Icon(Icons.notifications_active_rounded,
                            size: 18, color: ByteSqueezeColors.mint),
                    ],
                  ),
                  const SizedBox(height: 5),
                  Text(
                      'S${season.toString().padLeft(2, '0')}E${number.toString().padLeft(2, '0')}  ${episode['name'] ?? 'New episode'}',
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: ByteSqueezeColors.cyan)),
                  if ('${episode['airtime'] ?? ''}'.isNotEmpty) ...[
                    const SizedBox(height: 7),
                    Text('${episode['airtime']}',
                        style: const TextStyle(
                            color: ByteSqueezeColors.muted, fontSize: 12)),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
