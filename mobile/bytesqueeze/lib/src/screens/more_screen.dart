import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../theme.dart';
import '../widgets/common.dart';
import 'calendar_screen.dart';

class MoreScreen extends StatelessWidget {
  const MoreScreen({super.key, required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final nodeRows = asList(controller.nodes['nodes']);
    final online =
        nodeRows.where((row) => asMap(row)['online'] == true).length +
            (asMap(controller.nodes['local'])['online'] == false ? 0 : 1);
    final storageSummary = asMap(controller.storage['summary']);
    final eventRows = asList(controller.events['events']);
    return ListView(
      children: [
        PageInsets(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text('SERVER',
                  style: TextStyle(
                      color: ByteSqueezeColors.cyan,
                      fontSize: 11,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 1.6)),
              const SizedBox(height: 5),
              Text('Server', style: Theme.of(context).textTheme.headlineLarge),
              const SizedBox(height: 4),
              const Text('Workers, storage, activity, and this connection',
                  style: TextStyle(color: ByteSqueezeColors.muted)),
              const SizedBox(height: 18),
              SurfaceCard(
                gradient: const LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: [Color(0xFF123A72), Color(0xFF09172F)],
                ),
                borderColor: const Color(0xFF24568F),
                child: Row(
                  children: [
                    const BrandMark(size: 62, showName: false),
                    const SizedBox(width: 15),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                              controller.demoMode
                                  ? 'ByteSqueeze demo'
                                  : (controller.session?.deviceName ??
                                      'ByteSqueeze'),
                              style: Theme.of(context).textTheme.titleLarge),
                          const SizedBox(height: 3),
                          Text(controller.serverLabel,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                  color: ByteSqueezeColors.muted)),
                          const SizedBox(height: 8),
                          StatusPill(
                              label: controller.canControl
                                  ? 'Control access'
                                  : 'Read-only access',
                              color: controller.canControl
                                  ? ByteSqueezeColors.mint
                                  : ByteSqueezeColors.amber,
                              icon: Icons.shield_outlined),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              const SectionHeader(title: 'Server'),
              SurfaceCard(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Column(
                  children: [
                    _MoreTile(
                      icon: Icons.calendar_month_rounded,
                      color: ByteSqueezeColors.blue,
                      title: 'Upcoming episodes',
                      subtitle: 'Release calendar for tracked shows',
                      onTap: () => _open(
                          context, CalendarScreen(controller: controller)),
                    ),
                    _MoreTile(
                      icon: Icons.hub_rounded,
                      color: ByteSqueezeColors.cyan,
                      title: 'Encoding nodes',
                      subtitle: '$online online · ${nodeRows.length + 1} total',
                      onTap: () =>
                          _open(context, NodesPage(controller: controller)),
                    ),
                    _MoreTile(
                      icon: Icons.savings_outlined,
                      color: ByteSqueezeColors.mint,
                      title: 'Storage savings',
                      subtitle:
                          '${formatBytes(storageSummary['saved_bytes'])} reclaimed across ${storageSummary['count'] ?? 0} encodes',
                      onTap: () =>
                          _open(context, StoragePage(controller: controller)),
                    ),
                    _MoreTile(
                      icon: Icons.bolt_rounded,
                      color: ByteSqueezeColors.amber,
                      title: 'Event timeline',
                      subtitle: '${eventRows.length} recent server events',
                      onTap: () =>
                          _open(context, EventsPage(controller: controller)),
                    ),
                  ],
                ),
              ),
              const SectionHeader(title: 'ByteSqueeze'),
              SurfaceCard(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Column(
                  children: [
                    _MoreTile(
                      icon: Icons.security_rounded,
                      color: ByteSqueezeColors.blue,
                      title: 'Connection & security',
                      subtitle:
                          'Pairing scope, server address, and token storage',
                      onTap: () => _open(
                          context, ConnectionPage(controller: controller)),
                    ),
                    _MoreTile(
                      icon: Icons.info_outline_rounded,
                      color: ByteSqueezeColors.muted,
                      title: 'About',
                      subtitle: 'ByteSqueeze 0.3.12 · TSD 3.12',
                      onTap: () => showAboutDialog(
                        context: context,
                        applicationName: 'ByteSqueeze',
                        applicationVersion: '0.3.12',
                        applicationIcon: ClipRRect(
                          borderRadius: BorderRadius.circular(18),
                          child: Image.asset(
                              'assets/branding/bytesqueeze_icon.png',
                              width: 72,
                              height: 72),
                        ),
                        children: const [
                          Text(
                              'A cross-platform remote control for HandBrake TSD Helper. All encoding stays on the Docker-hosted server.')
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 18),
              OutlinedButton.icon(
                onPressed: () => _disconnect(context),
                icon: const Icon(Icons.logout_rounded,
                    color: ByteSqueezeColors.danger),
                label: Text(
                    controller.demoMode
                        ? 'Exit demo'
                        : 'Disconnect this device',
                    style: const TextStyle(color: ByteSqueezeColors.danger)),
                style: OutlinedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 15),
                  side: BorderSide(
                      color: ByteSqueezeColors.danger.withValues(alpha: .45)),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(16)),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  void _open(BuildContext context, Widget page) {
    Navigator.push(context, MaterialPageRoute(builder: (_) => page));
  }

  Future<void> _disconnect(BuildContext context) async {
    final confirmed = controller.demoMode ||
        await showDialog<bool>(
              context: context,
              builder: (context) => AlertDialog(
                title: const Text('Disconnect ByteSqueeze?'),
                content: const Text(
                    'The server address and mobile tokens will be removed from this device. You can pair it again later.'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('Cancel')),
                  FilledButton(
                      onPressed: () => Navigator.pop(context, true),
                      child: const Text('Disconnect')),
                ],
              ),
            ) ==
            true;
    if (confirmed) await controller.disconnect();
  }
}

class _MoreTile extends StatelessWidget {
  const _MoreTile(
      {required this.icon,
      required this.color,
      required this.title,
      required this.subtitle,
      required this.onTap});

  final IconData icon;
  final Color color;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      onTap: onTap,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 4),
      leading: DecoratedBox(
        decoration: BoxDecoration(
            color: color.withValues(alpha: .12),
            borderRadius: BorderRadius.circular(12)),
        child: Padding(
            padding: const EdgeInsets.all(10), child: Icon(icon, color: color)),
      ),
      title: Text(title, style: const TextStyle(fontWeight: FontWeight.w700)),
      subtitle: Text(subtitle,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(color: ByteSqueezeColors.muted, fontSize: 12)),
      trailing: const Icon(Icons.chevron_right_rounded,
          color: ByteSqueezeColors.muted),
    );
  }
}

class _DetailScaffold extends StatelessWidget {
  const _DetailScaffold(
      {required this.title, required this.child, this.actions});

  final String title;
  final Widget child;
  final List<Widget>? actions;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(title), actions: actions),
      body: DecoratedBox(
          decoration: const BoxDecoration(gradient: ByteSqueezeColors.backdrop),
          child: child),
    );
  }
}

class NodesPage extends StatelessWidget {
  const NodesPage({super.key, required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final local = asMap(controller.nodes['local']);
    final nodes = asList(controller.nodes['nodes']).map(asMap).toList();
    final all = [local, ...nodes].where((row) => row.isNotEmpty).toList();
    return _DetailScaffold(
      title: 'Encoding nodes',
      actions: [
        IconButton(
            onPressed: controller.refreshAll,
            icon: const Icon(Icons.refresh_rounded))
      ],
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          for (var index = 0; index < all.length; index++)
            Padding(
              padding: const EdgeInsets.only(bottom: 11),
              child: _NodeCard(node: all[index], local: index == 0),
            ),
        ],
      ),
    );
  }
}

class _NodeCard extends StatelessWidget {
  const _NodeCard({required this.node, required this.local});

  final Map<String, dynamic> node;
  final bool local;

  @override
  Widget build(BuildContext context) {
    final online = node['online'] != false;
    final status = '${node['status'] ?? (online ? 'idle' : 'offline')}';
    final color = statusColor(online ? status : 'offline');
    return SurfaceCard(
      child: Row(
        children: [
          Stack(
            clipBehavior: Clip.none,
            children: [
              DecoratedBox(
                decoration: BoxDecoration(
                    color: ByteSqueezeColors.blue.withValues(alpha: .12),
                    borderRadius: BorderRadius.circular(15)),
                child: const Padding(
                    padding: EdgeInsets.all(13),
                    child: Icon(Icons.computer_rounded,
                        color: ByteSqueezeColors.cyan, size: 28)),
              ),
              Positioned(
                  right: -2,
                  bottom: -2,
                  child: Container(
                      width: 13,
                      height: 13,
                      decoration: BoxDecoration(
                          color: online
                              ? ByteSqueezeColors.mint
                              : ByteSqueezeColors.danger,
                          shape: BoxShape.circle,
                          border: Border.all(
                              color: ByteSqueezeColors.surface, width: 2)))),
            ],
          ),
          const SizedBox(width: 15),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${node['name'] ?? (local ? 'TSD Main' : 'Worker')}',
                    style: const TextStyle(fontWeight: FontWeight.w700)),
                const SizedBox(height: 4),
                Text(
                    local
                        ? 'Controller · protocol ${node['protocol_version'] ?? 2}'
                        : 'Linked worker · protocol ${node['protocol_version'] ?? 2}',
                    style: const TextStyle(
                        color: ByteSqueezeColors.muted, fontSize: 12)),
              ],
            ),
          ),
          StatusPill(label: online ? status : 'offline', color: color),
        ],
      ),
    );
  }
}

class StoragePage extends StatelessWidget {
  const StoragePage({super.key, required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final summary = asMap(controller.storage['summary']);
    final rows = asList(controller.storage['encodes']).map(asMap).toList();
    return _DetailScaffold(
      title: 'Storage savings',
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          SurfaceCard(
            gradient: const LinearGradient(
                colors: [Color(0xFF0E5C58), Color(0xFF0A2235)]),
            borderColor: const Color(0xFF18796F),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(Icons.savings_rounded,
                    color: ByteSqueezeColors.mint, size: 34),
                const SizedBox(height: 22),
                Text(formatBytes(summary['saved_bytes']),
                    style: Theme.of(context).textTheme.displaySmall),
                const Text('total space reclaimed',
                    style: TextStyle(color: ByteSqueezeColors.muted)),
                const SizedBox(height: 10),
                Text(
                    '${summary['count'] ?? 0} completed encodes · ${formatDuration(summary['total_runtime_seconds'])} processing time',
                    style: const TextStyle(color: ByteSqueezeColors.mint)),
              ],
            ),
          ),
          const SectionHeader(title: 'Recent savings'),
          if (rows.isEmpty)
            const EmptyState(
                icon: Icons.savings_outlined,
                title: 'No completed encodes',
                message:
                    'Savings appear after TSD verifies an output and records the result.')
          else
            ...rows.map((row) => Padding(
                  padding: const EdgeInsets.only(bottom: 9),
                  child: SurfaceCard(
                    padding: const EdgeInsets.all(15),
                    child: Row(
                      children: [
                        const CircleAvatar(
                            backgroundColor: Color(0x223FE1AE),
                            child: Icon(Icons.arrow_downward_rounded,
                                color: ByteSqueezeColors.mint)),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(fileName(row['src']),
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(
                                      fontWeight: FontWeight.w700)),
                              const SizedBox(height: 3),
                              Text(
                                  '${row['encoder'] ?? row['preset'] ?? 'encode'} · ${relativeTime(row['ts'])}',
                                  style: const TextStyle(
                                      color: ByteSqueezeColors.muted,
                                      fontSize: 12)),
                            ],
                          ),
                        ),
                        Text(formatBytes(row['saved_bytes']),
                            style: const TextStyle(
                                color: ByteSqueezeColors.mint,
                                fontWeight: FontWeight.w700)),
                      ],
                    ),
                  ),
                )),
        ],
      ),
    );
  }
}

class EventsPage extends StatelessWidget {
  const EventsPage({super.key, required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final rows = asList(controller.events['events']).map(asMap).toList();
    return _DetailScaffold(
      title: 'Event timeline',
      child: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: rows.length,
        itemBuilder: (context, index) {
          final event = rows[index];
          final level = '${event['level'] ?? 'info'}';
          final color = level == 'error'
              ? ByteSqueezeColors.danger
              : (level == 'warn'
                  ? ByteSqueezeColors.amber
                  : ByteSqueezeColors.cyan);
          return Padding(
            padding: const EdgeInsets.only(bottom: 9),
            child: SurfaceCard(
              padding: const EdgeInsets.all(15),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                      width: 10,
                      height: 10,
                      margin: const EdgeInsets.only(top: 5),
                      decoration:
                          BoxDecoration(color: color, shape: BoxShape.circle)),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                            '${event['message'] ?? event['type'] ?? 'Server event'}',
                            style:
                                const TextStyle(fontWeight: FontWeight.w600)),
                        const SizedBox(height: 5),
                        Text(
                            '${event['type'] ?? 'event'} · ${relativeTime(event['ts'])}',
                            style: const TextStyle(
                                color: ByteSqueezeColors.muted, fontSize: 12)),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

class ConnectionPage extends StatefulWidget {
  const ConnectionPage({super.key, required this.controller});

  final AppController controller;

  @override
  State<ConnectionPage> createState() => _ConnectionPageState();
}

class _ConnectionPageState extends State<ConnectionPage> {
  late final TextEditingController _primary;
  late final TextEditingController _fallback;
  bool _saving = false;

  AppController get controller => widget.controller;

  @override
  void initState() {
    super.initState();
    _primary = TextEditingController(text: controller.session?.baseUrl ?? '');
    _fallback = TextEditingController(
        text: controller.session?.fallbackBaseUrl ?? '');
  }

  @override
  void dispose() {
    _primary.dispose();
    _fallback.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return _DetailScaffold(
      title: 'Connection & security',
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          SurfaceCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const StatusPill(
                    label: 'Bearer token pairing',
                    color: ByteSqueezeColors.mint,
                    icon: Icons.lock_rounded),
                const SizedBox(height: 18),
                _KeyValue(label: 'Server', value: controller.serverLabel),
                _KeyValue(
                    label: 'Current route',
                    value: controller.demoMode
                        ? 'Demo'
                        : controller.api.activeBaseUrl),
                _KeyValue(
                    label: 'Device',
                    value: controller.demoMode
                        ? 'Demo mode'
                        : (controller.session?.deviceName ?? 'ByteSqueeze')),
                _KeyValue(
                    label: 'Permission',
                    value: controller.canControl
                        ? 'Read and control'
                        : 'Read only'),
                _KeyValue(
                    label: 'Device ID',
                    value: controller.demoMode
                        ? 'demo'
                        : (controller.session?.deviceId ?? '—')),
              ],
            ),
          ),
          const SizedBox(height: 13),
          SurfaceCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text('Automatic address fallback',
                    style: Theme.of(context).textTheme.titleLarge),
                const SizedBox(height: 5),
                const Text(
                    'ByteSqueeze tries the current route, then your home and away addresses. It switches only when a connection fails.',
                    style: TextStyle(color: ByteSqueezeColors.muted)),
                const SizedBox(height: 15),
                TextField(
                  controller: _primary,
                  enabled: !controller.demoMode,
                  keyboardType: TextInputType.url,
                  autocorrect: false,
                  decoration: const InputDecoration(
                    labelText: 'Home / primary address',
                    hintText: 'http://192.168.1.50:8080',
                    prefixIcon: Icon(Icons.home_outlined),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _fallback,
                  enabled: !controller.demoMode,
                  keyboardType: TextInputType.url,
                  autocorrect: false,
                  decoration: const InputDecoration(
                    labelText: 'Away / Tailscale address (optional)',
                    hintText: 'http://100.x.x.x:8080',
                    prefixIcon: Icon(Icons.route_rounded),
                  ),
                ),
                const SizedBox(height: 15),
                FilledButton.icon(
                  onPressed: controller.demoMode || _saving ? null : _save,
                  icon: _saving
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.save_outlined),
                  label: const Text('Save connection addresses'),
                ),
              ],
            ),
          ),
          const SizedBox(height: 13),
          const SurfaceCard(
            borderColor: ByteSqueezeColors.amber,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(Icons.security_rounded, color: ByteSqueezeColors.amber),
                SizedBox(width: 12),
                Expanded(
                    child: Text(
                        'Tokens are kept in platform secure storage. For remote access, put TSD behind an authenticated HTTPS reverse proxy instead of exposing port 8080 directly.')),
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
      await controller.updateServerAddresses(_primary.text, _fallback.text);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text(
              'Connection addresses saved. Automatic fallback is active.')));
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

class _KeyValue extends StatelessWidget {
  const _KeyValue({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 13),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label,
              style: const TextStyle(
                  color: ByteSqueezeColors.muted, fontSize: 12)),
          const SizedBox(height: 3),
          SelectableText(value,
              style: const TextStyle(fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}
