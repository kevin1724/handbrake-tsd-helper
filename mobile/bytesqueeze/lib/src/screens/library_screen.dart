import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../theme.dart';
import '../widgets/common.dart';

class LibraryScreen extends StatefulWidget {
  const LibraryScreen({super.key, required this.controller});

  final AppController controller;

  @override
  State<LibraryScreen> createState() => _LibraryScreenState();
}

class _LibraryScreenState extends State<LibraryScreen> {
  final _search = TextEditingController();
  bool _shows = false;

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final all = asList(widget.controller.library[_shows ? 'shows' : 'movies'])
        .map(asMap)
        .toList();
    final query = _search.text.trim().toLowerCase();
    final items = query.isEmpty
        ? all
        : all
            .where((item) => '${item['title'] ?? ''} ${item['year'] ?? ''}'
                .toLowerCase()
                .contains(query))
            .toList();
    final stats = asMap(widget.controller.library['stats']);
    final configured = widget.controller.library['configured'] != false;

    return RefreshIndicator(
      onRefresh: widget.controller.canControl
          ? widget.controller.refreshLibrary
          : widget.controller.refreshAll,
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
                            const Text('YOUR MEDIA',
                                style: TextStyle(
                                    color: ByteSqueezeColors.cyan,
                                    fontSize: 11,
                                    fontWeight: FontWeight.w800,
                                    letterSpacing: 1.6)),
                            const SizedBox(height: 5),
                            Text('Library',
                                style:
                                    Theme.of(context).textTheme.headlineLarge),
                            const SizedBox(height: 4),
                            Text(
                              '${(stats['movies'] as num?)?.toInt() ?? all.length} movies · ${(stats['shows'] as num?)?.toInt() ?? 0} shows · ${(stats['episodes'] as num?)?.toInt() ?? 0} episodes',
                              style: const TextStyle(
                                  color: ByteSqueezeColors.muted),
                            ),
                          ],
                        ),
                      ),
                      IconButton.filledTonal(
                        tooltip: 'Refresh library on server',
                        onPressed: widget.controller.canControl &&
                                !widget.controller.busy
                            ? () => _run(widget.controller.refreshLibrary)
                            : null,
                        icon: const Icon(Icons.sync_rounded),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  SegmentedButton<bool>(
                    segments: const [
                      ButtonSegment(
                          value: false,
                          icon: Icon(Icons.movie_outlined),
                          label: Text('Movies')),
                      ButtonSegment(
                          value: true,
                          icon: Icon(Icons.tv_rounded),
                          label: Text('Shows')),
                    ],
                    selected: {_shows},
                    onSelectionChanged: (value) =>
                        setState(() => _shows = value.first),
                    showSelectedIcon: false,
                    style: ButtonStyle(
                        shape: WidgetStatePropertyAll(RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14)))),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _search,
                    onChanged: (_) => setState(() {}),
                    decoration: InputDecoration(
                      hintText: _shows ? 'Search shows' : 'Search movies',
                      prefixIcon: const Icon(Icons.search_rounded),
                      suffixIcon: _search.text.isEmpty
                          ? null
                          : IconButton(
                              onPressed: () {
                                _search.clear();
                                setState(() {});
                              },
                              icon: const Icon(Icons.close_rounded),
                            ),
                    ),
                  ),
                  if (!configured) ...[
                    const SizedBox(height: 14),
                    const SurfaceCard(
                      borderColor: ByteSqueezeColors.amber,
                      child: Row(
                        children: [
                          Icon(Icons.folder_off_outlined,
                              color: ByteSqueezeColors.amber),
                          SizedBox(width: 12),
                          Expanded(
                              child: Text(
                                  'Map Movies and Shows folders in the TSD web settings, then refresh here.')),
                        ],
                      ),
                    ),
                  ],
                  if (query.isEmpty && items.isNotEmpty) ...[
                    SectionHeader(
                      title: _shows ? 'Tracked shows' : 'Recently added',
                      subtitle: _shows
                          ? 'Favorites with release and download monitoring'
                          : 'Latest files discovered on mapped drives',
                    ),
                    _MediaRail(
                      items: (_shows
                              ? all
                                  .where((item) => item['tracked'] == true)
                                  .toList()
                              : asList(asMap(widget.controller
                                      .library['catalog'])['recently_added'])
                                  .map(asMap)
                                  .where((item) => item['type'] == 'movie')
                                  .toList())
                          .take(12)
                          .toList(),
                      isShow: _shows,
                      onTap: _openDetails,
                    ),
                    const SectionHeader(
                      title: 'Complete catalog',
                      subtitle: 'Every title currently found on mapped drives',
                    ),
                  ],
                  const SizedBox(height: 16),
                  if (items.isEmpty)
                    EmptyState(
                      icon: _shows
                          ? Icons.tv_off_outlined
                          : Icons.movie_filter_outlined,
                      title:
                          query.isEmpty ? 'Nothing scanned yet' : 'No matches',
                      message: query.isEmpty
                          ? 'Run a library refresh after mapping media folders in TSD.'
                          : 'Try another title or year.',
                    )
                  else
                    LayoutBuilder(
                      builder: (context, constraints) {
                        final width = constraints.maxWidth;
                        final columns = width >= 1100
                            ? 7
                            : (width >= 820 ? 5 : (width >= 540 ? 4 : 2));
                        return GridView.builder(
                          shrinkWrap: true,
                          physics: const NeverScrollableScrollPhysics(),
                          gridDelegate:
                              SliverGridDelegateWithFixedCrossAxisCount(
                            crossAxisCount: columns,
                            mainAxisSpacing: 14,
                            crossAxisSpacing: 12,
                            childAspectRatio: .58,
                          ),
                          itemCount: items.length,
                          itemBuilder: (context, index) => _MediaTile(
                            item: items[index],
                            isShow: _shows,
                            onTap: () => _openDetails(items[index]),
                          ),
                        );
                      },
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _openDetails(Map<String, dynamic> item) async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      backgroundColor: ByteSqueezeColors.navy,
      showDragHandle: true,
      builder: (context) => _MediaDetails(
          controller: widget.controller, item: item, isShow: _shows),
    );
    if (mounted) setState(() {});
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

class _MediaRail extends StatelessWidget {
  const _MediaRail({
    required this.items,
    required this.isShow,
    required this.onTap,
  });

  final List<Map<String, dynamic>> items;
  final bool isShow;
  final ValueChanged<Map<String, dynamic>> onTap;

  @override
  Widget build(BuildContext context) {
    if (items.isEmpty) {
      return SurfaceCard(
        child: Text(
          isShow
              ? 'Track shows to keep favorites and upcoming episodes here.'
              : 'Newly discovered movies appear here after the next scan.',
          style: const TextStyle(color: ByteSqueezeColors.muted),
        ),
      );
    }
    return SizedBox(
      height: 222,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: items.length,
        separatorBuilder: (_, __) => const SizedBox(width: 11),
        itemBuilder: (context, index) {
          final item = items[index];
          return SizedBox(
            width: 126,
            child: InkWell(
              onTap: () => onTap(item),
              borderRadius: BorderRadius.circular(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: PosterArt(item: item, borderRadius: 16)),
                  const SizedBox(height: 7),
                  Text('${item['title'] ?? 'Unknown'}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontWeight: FontWeight.w700)),
                  Text('${item['year'] ?? ''}',
                      style: const TextStyle(
                          color: ByteSqueezeColors.muted, fontSize: 11.5)),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

class _MediaTile extends StatelessWidget {
  const _MediaTile(
      {required this.item, required this.isShow, required this.onTap});

  final Map<String, dynamic> item;
  final bool isShow;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final prediction = asMap(item['prediction']);
    final savings = (prediction['savings_percent'] as num?)?.round();
    return Material(
      color: ByteSqueezeColors.surface.withValues(alpha: .72),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(19),
        side: const BorderSide(color: ByteSqueezeColors.line),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Stack(
                fit: StackFit.expand,
                children: [
                  PosterArt(item: item, borderRadius: 0),
                  const DecoratedBox(
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        begin: Alignment.center,
                        end: Alignment.bottomCenter,
                        colors: [Colors.transparent, Color(0x88030A15)],
                      ),
                    ),
                  ),
                  Positioned(
                    top: 8,
                    right: 8,
                    child: isShow && item['tracked'] == true
                        ? const StatusPill(
                            label: 'Tracked',
                            color: ByteSqueezeColors.mint,
                            icon: Icons.notifications_active_outlined)
                        : savings != null
                            ? StatusPill(
                                label: '$savings% save',
                                color: ByteSqueezeColors.cyan)
                            : const SizedBox.shrink(),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(11, 9, 11, 10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('${item['title'] ?? 'Unknown'}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontWeight: FontWeight.w800)),
                  const SizedBox(height: 3),
                  Text(
                    isShow
                        ? '${item['season_count'] ?? 0} seasons · ${item['episode_count'] ?? 0} episodes'
                        : '${item['year'] ?? 'Unknown year'} · ${formatBytes(item['size_bytes'] ?? item['total_size_bytes'])}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        color: ByteSqueezeColors.muted, fontSize: 11.5),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _MediaDetails extends StatefulWidget {
  const _MediaDetails(
      {required this.controller, required this.item, required this.isShow});

  final AppController controller;
  final Map<String, dynamic> item;
  final bool isShow;

  @override
  State<_MediaDetails> createState() => _MediaDetailsState();
}

class _MediaDetailsState extends State<_MediaDetails> {
  bool _working = false;
  String _queueTarget = 'local:';

  List<String> get _paths {
    if (widget.isShow) {
      return asList(widget.item['files'])
          .map((row) => '${asMap(row)['path'] ?? ''}')
          .where((path) => path.isNotEmpty)
          .toList();
    }
    final values = asList(widget.item['paths'])
        .map((value) => '$value')
        .where((path) => path.isNotEmpty)
        .toList();
    final path = '${widget.item['path'] ?? ''}';
    if (values.isEmpty && path.isNotEmpty) values.add(path);
    return values;
  }

  Future<void> _queue(String preset) async {
    setState(() => _working = true);
    try {
      final parts = _queueTarget.split(':');
      final mode = parts.first;
      final nodeId = parts.length > 1 ? parts.sublist(1).join(':') : '';
      await widget.controller.queuePaths(
        _paths,
        preset: preset,
        mode: mode,
        nodeId: nodeId,
      );
      if (!mounted) return;
      final messenger = ScaffoldMessenger.of(context);
      Navigator.pop(context);
      messenger.showSnackBar(
        SnackBar(
          content:
              Text('${widget.item['title']} queued for ${_targetLabel()}.'),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$error')));
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  String _targetLabel() {
    if (_queueTarget == 'local:') return 'this server';
    if (_queueTarget == 'best:') return 'the best available node';
    final id = _queueTarget.substring('node:'.length);
    for (final value in asList(widget.controller.nodes['nodes'])) {
      final node = asMap(value);
      if ('${node['id'] ?? ''}' == id) {
        return '${node['name'] ?? 'the selected node'}';
      }
    }
    return 'the selected node';
  }

  Future<void> _track(bool value) async {
    setState(() => widget.item['tracked'] = value);
    try {
      await widget.controller.trackShow(widget.item, value);
    } catch (error) {
      if (!mounted) return;
      setState(() => widget.item['tracked'] = !value);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$error')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final files = asList(widget.item['files']);
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: .88,
      minChildSize: .5,
      maxChildSize: .96,
      builder: (context, scrollController) => ListView(
        controller: scrollController,
        padding: const EdgeInsets.fromLTRB(20, 6, 20, 40),
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                  width: 118,
                  height: 177,
                  child: PosterArt(item: widget.item, borderRadius: 16)),
              const SizedBox(width: 18),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('${widget.item['title'] ?? 'Unknown'}',
                        style: Theme.of(context).textTheme.headlineSmall),
                    const SizedBox(height: 7),
                    Text('${widget.item['year'] ?? ''}',
                        style: const TextStyle(color: ByteSqueezeColors.muted)),
                    const SizedBox(height: 14),
                    Wrap(
                      spacing: 7,
                      runSpacing: 7,
                      children: [
                        if (widget.isShow)
                          StatusPill(
                              label:
                                  '${widget.item['episode_count'] ?? files.length} episodes',
                              icon: Icons.tv_rounded),
                        if (!widget.isShow)
                          StatusPill(
                              label: formatBytes(widget.item['size_bytes'] ??
                                  widget.item['total_size_bytes']),
                              icon: Icons.storage_rounded),
                        if (widget.item['quality'] != null)
                          StatusPill(
                              label: '${widget.item['quality']}',
                              color: ByteSqueezeColors.mint),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
          if (widget.isShow) ...[
            const SizedBox(height: 18),
            SurfaceCard(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
              child: SwitchListTile.adaptive(
                value: widget.item['tracked'] == true,
                onChanged: widget.controller.canControl ? _track : null,
                title: const Text('Track new episodes',
                    style: TextStyle(fontWeight: FontWeight.w700)),
                subtitle: const Text(
                    'Add release dates to Calendar and watch mapped drives for new files.'),
                secondary: const Icon(Icons.notifications_active_outlined,
                    color: ByteSqueezeColors.cyan),
              ),
            ),
            if (widget.item['tracked'] == true)
              SurfaceCard(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                child: Column(
                  children: [
                    SwitchListTile.adaptive(
                      contentPadding: EdgeInsets.zero,
                      value: widget.item['monitor_releases'] != false,
                      onChanged: widget.controller.canControl
                          ? (value) async {
                              setState(() =>
                                  widget.item['monitor_releases'] = value);
                              await widget.controller
                                  .trackShow(widget.item, true);
                            }
                          : null,
                      title: const Text('Upcoming episode calendar'),
                      subtitle:
                          const Text('Show known release dates from TVmaze.'),
                      secondary: const Icon(Icons.calendar_month_outlined),
                    ),
                    const Divider(height: 1),
                    SwitchListTile.adaptive(
                      contentPadding: EdgeInsets.zero,
                      value: widget.item['auto_queue_downloads'] != false,
                      onChanged: widget.controller.canControl
                          ? (value) async {
                              setState(() =>
                                  widget.item['auto_queue_downloads'] = value);
                              await widget.controller
                                  .trackShow(widget.item, true);
                            }
                          : null,
                      title: const Text('Auto-queue finished downloads'),
                      subtitle: const Text(
                          'Wait until a new file stops changing, then queue it.'),
                      secondary: const Icon(Icons.download_done_rounded),
                    ),
                  ],
                ),
              ),
          ],
          const SectionHeader(
              title: 'Remote encode',
              subtitle: 'The Docker server performs all encoding work'),
          DropdownButtonFormField<String>(
            initialValue: _queueTarget,
            decoration: const InputDecoration(
              labelText: 'Encoding node',
              prefixIcon: Icon(Icons.hub_outlined),
            ),
            items: [
              const DropdownMenuItem(
                value: 'local:',
                child: Text('This server (local)'),
              ),
              if (asList(widget.controller.nodes['nodes'])
                  .map(asMap)
                  .any((row) => row['online'] == true))
                const DropdownMenuItem(
                  value: 'best:',
                  child: Text('Best available node'),
                ),
              ...asList(widget.controller.nodes['nodes'])
                  .map(asMap)
                  .where((row) => row['online'] == true)
                  .map((row) => DropdownMenuItem(
                        value: 'node:${row['id']}',
                        child: Text('${row['name'] ?? 'Worker node'}'),
                      )),
            ],
            onChanged: _working
                ? null
                : (value) => setState(() => _queueTarget = value ?? 'local:'),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  onPressed: widget.controller.canControl && !_working
                      ? () => _queue('smart')
                      : null,
                  icon: _working
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.auto_awesome_rounded),
                  label: const Text('Queue Smart Preset'),
                ),
              ),
              const SizedBox(width: 9),
              PopupMenuButton<String>(
                enabled: widget.controller.canControl && !_working,
                tooltip: 'Other server presets',
                onSelected: _queue,
                itemBuilder: (context) => const [
                  PopupMenuItem(value: 'auto', child: Text('Automatic preset')),
                  PopupMenuItem(value: '1080', child: Text('1080p preset')),
                  PopupMenuItem(value: '4k', child: Text('4K preset')),
                ],
                child: const DecoratedBox(
                  decoration: BoxDecoration(
                      color: ByteSqueezeColors.raised,
                      borderRadius: BorderRadius.all(Radius.circular(14))),
                  child: Padding(
                      padding: EdgeInsets.all(14),
                      child: Icon(Icons.more_horiz_rounded)),
                ),
              ),
            ],
          ),
          if (files.isNotEmpty) ...[
            SectionHeader(
                title: widget.isShow ? 'Episodes' : 'Files',
                subtitle: '${files.length} media files'),
            SurfaceCard(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Column(
                children: files.take(100).map((row) {
                  final file = asMap(row);
                  return ListTile(
                    leading: CircleAvatar(
                      backgroundColor:
                          ByteSqueezeColors.blue.withValues(alpha: .12),
                      child: Text('${file['episode'] ?? '•'}',
                          style: const TextStyle(
                              color: ByteSqueezeColors.cyan,
                              fontWeight: FontWeight.w700)),
                    ),
                    title: Text(fileName(file['path']),
                        maxLines: 1, overflow: TextOverflow.ellipsis),
                    subtitle: Text(
                        'Season ${file['season'] ?? '—'} · ${formatBytes(file['size_bytes'])}',
                        style: const TextStyle(color: ByteSqueezeColors.muted)),
                  );
                }).toList(),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
