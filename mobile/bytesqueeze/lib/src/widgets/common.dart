import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme.dart';

Map<String, dynamic> asMap(dynamic value) =>
    value is Map<String, dynamic> ? value : <String, dynamic>{};
List<dynamic> asList(dynamic value) => value is List ? value : <dynamic>[];

String fileName(dynamic path) {
  final value = '${path ?? ''}'.replaceAll('\\', '/');
  return value.split('/').where((part) => part.isNotEmpty).lastOrNull ??
      'Unknown media';
}

String formatBytes(dynamic value, {int decimals = 1}) {
  final bytes =
      value is num ? value.toDouble() : double.tryParse('$value') ?? 0;
  if (bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  final exponent =
      math.min(units.length - 1, (math.log(bytes) / math.log(1024)).floor());
  final amount = bytes / math.pow(1024, exponent);
  return '${amount.toStringAsFixed(exponent == 0 ? 0 : decimals)} ${units[exponent]}';
}

String formatDuration(dynamic seconds) {
  final total =
      seconds is num ? seconds.round() : int.tryParse('$seconds') ?? 0;
  if (total <= 0) return '—';
  final hours = total ~/ 3600;
  final minutes = (total % 3600) ~/ 60;
  if (hours > 0) return '${hours}h ${minutes}m';
  return '${math.max(1, minutes)}m';
}

String relativeTime(dynamic timestamp) {
  final seconds = timestamp is num
      ? timestamp.toDouble()
      : double.tryParse('$timestamp') ?? 0;
  if (seconds <= 0) return 'No recent activity';
  final difference = DateTime.now().difference(
      DateTime.fromMillisecondsSinceEpoch((seconds * 1000).round()));
  if (difference.inMinutes < 1) return 'Just now';
  if (difference.inHours < 1) return '${difference.inMinutes}m ago';
  if (difference.inDays < 1) return '${difference.inHours}h ago';
  return '${difference.inDays}d ago';
}

Color statusColor(String status) {
  switch (status.toLowerCase()) {
    case 'running':
    case 'online':
    case 'done':
    case 'success':
      return ByteSqueezeColors.mint;
    case 'queued':
    case 'waiting_to_upload':
      return ByteSqueezeColors.cyan;
    case 'error':
    case 'offline':
    case 'canceled':
      return ByteSqueezeColors.danger;
    default:
      return ByteSqueezeColors.amber;
  }
}

class PageInsets extends StatelessWidget {
  const PageInsets({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 1280),
        child: Padding(
          padding: EdgeInsets.fromLTRB(
            MediaQuery.sizeOf(context).width < 600 ? 16 : 24,
            8,
            MediaQuery.sizeOf(context).width < 600 ? 16 : 24,
            110,
          ),
          child: child,
        ),
      ),
    );
  }
}

class SurfaceCard extends StatelessWidget {
  const SurfaceCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(18),
    this.onTap,
    this.gradient,
    this.borderColor,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final VoidCallback? onTap;
  final Gradient? gradient;
  final Color? borderColor;

  @override
  Widget build(BuildContext context) {
    final radius = BorderRadius.circular(22);
    return Material(
      color: Colors.transparent,
      borderRadius: radius,
      clipBehavior: Clip.antiAlias,
      child: Ink(
        decoration: BoxDecoration(
          color: gradient == null ? ByteSqueezeColors.surface : null,
          gradient: gradient,
          borderRadius: radius,
          border: Border.all(
            color: borderColor ?? ByteSqueezeColors.line,
            width: .7,
          ),
          boxShadow: const [
            BoxShadow(
              color: Color(0x33000000),
              blurRadius: 22,
              offset: Offset(0, 12),
            ),
          ],
        ),
        child: InkWell(
          onTap: onTap,
          borderRadius: radius,
          child: Padding(padding: padding, child: child),
        ),
      ),
    );
  }
}

class SectionHeader extends StatelessWidget {
  const SectionHeader(
      {super.key, required this.title, this.subtitle, this.trailing});

  final String title;
  final String? subtitle;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 12, bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: Theme.of(context).textTheme.titleLarge),
                if (subtitle != null) ...[
                  const SizedBox(height: 3),
                  Text(subtitle!,
                      style: const TextStyle(
                          color: ByteSqueezeColors.muted, fontSize: 13)),
                ],
              ],
            ),
          ),
          if (trailing != null) trailing!,
        ],
      ),
    );
  }
}

class StatusPill extends StatelessWidget {
  const StatusPill(
      {super.key,
      required this.label,
      this.color = ByteSqueezeColors.cyan,
      this.icon});

  final String label;
  final Color color;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: color.withValues(alpha: .12),
        border: Border.all(color: color.withValues(alpha: .34)),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null) ...[
              Icon(icon, color: color, size: 14),
              const SizedBox(width: 5)
            ],
            Text(label,
                style: TextStyle(
                    color: color, fontSize: 12, fontWeight: FontWeight.w700)),
          ],
        ),
      ),
    );
  }
}

class MetricCard extends StatelessWidget {
  const MetricCard({
    super.key,
    required this.label,
    required this.value,
    required this.icon,
    this.color = ByteSqueezeColors.cyan,
    this.detail,
  });

  final String label;
  final String value;
  final IconData icon;
  final Color color;
  final String? detail;

  @override
  Widget build(BuildContext context) {
    return SurfaceCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          DecoratedBox(
            decoration: BoxDecoration(
                color: color.withValues(alpha: .12),
                borderRadius: BorderRadius.circular(12)),
            child: Padding(
                padding: const EdgeInsets.all(9),
                child: Icon(icon, color: color, size: 20)),
          ),
          const Spacer(),
          Text(value, style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 3),
          Text(label,
              style: const TextStyle(
                  color: ByteSqueezeColors.muted, fontWeight: FontWeight.w600)),
          if (detail != null) ...[
            const SizedBox(height: 5),
            Text(detail!,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                    color: ByteSqueezeColors.muted, fontSize: 11)),
          ],
        ],
      ),
    );
  }
}

class BrandMark extends StatelessWidget {
  const BrandMark({super.key, this.size = 38, this.showName = true});

  final double size;
  final bool showName;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(size * .24),
          child: Image.asset('assets/branding/bytesqueeze_icon.png',
              width: size, height: size),
        ),
        if (showName) ...[
          const SizedBox(width: 10),
          Text('ByteSqueeze', style: Theme.of(context).textTheme.titleLarge),
        ],
      ],
    );
  }
}

class PosterArt extends StatelessWidget {
  const PosterArt({super.key, required this.item, this.borderRadius = 18});

  final Map<String, dynamic> item;
  final double borderRadius;

  @override
  Widget build(BuildContext context) {
    final url = '${item['poster_url'] ?? ''}'.trim();
    final title = '${item['title'] ?? 'Media'}';
    final hue = ((item['demo_hue'] as num?)?.toDouble() ??
        (title.hashCode.abs() % 360).toDouble());
    final first = HSVColor.fromAHSV(1, hue, .78, .88).toColor();
    final second = HSVColor.fromAHSV(1, (hue + 42) % 360, .82, .32).toColor();
    final fallback = DecoratedBox(
      decoration: BoxDecoration(
        gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [first, second, ByteSqueezeColors.navy]),
      ),
      child: Stack(
        fit: StackFit.expand,
        children: [
          Positioned(
              right: -28,
              top: -24,
              child: Icon(Icons.movie_filter_rounded,
                  size: 120, color: Colors.white.withValues(alpha: .10))),
          Align(
            alignment: Alignment.bottomLeft,
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Text(
                title,
                maxLines: 4,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w800,
                    height: 1.05,
                    shadows: [Shadow(blurRadius: 12, color: Colors.black)]),
              ),
            ),
          ),
        ],
      ),
    );
    return ClipRRect(
      borderRadius: BorderRadius.circular(borderRadius),
      child: url.isEmpty
          ? fallback
          : Image.network(
              url,
              fit: BoxFit.cover,
              errorBuilder: (_, __, ___) => fallback,
              loadingBuilder: (context, child, progress) => progress == null
                  ? child
                  : DecoratedBox(
                      decoration:
                          const BoxDecoration(color: ByteSqueezeColors.surface),
                      child: Center(
                        child: SizedBox(
                          width: 24,
                          height: 24,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            value: progress.expectedTotalBytes == null
                                ? null
                                : progress.cumulativeBytesLoaded /
                                    progress.expectedTotalBytes!,
                          ),
                        ),
                      ),
                    ),
            ),
    );
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState(
      {super.key,
      required this.icon,
      required this.title,
      required this.message,
      this.action});

  final IconData icon;
  final String title;
  final String message;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 30, vertical: 70),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 54, color: ByteSqueezeColors.muted),
            const SizedBox(height: 18),
            Text(title,
                style: Theme.of(context).textTheme.titleLarge,
                textAlign: TextAlign.center),
            const SizedBox(height: 8),
            Text(message,
                style: const TextStyle(color: ByteSqueezeColors.muted),
                textAlign: TextAlign.center),
            if (action != null) ...[const SizedBox(height: 20), action!],
          ],
        ),
      ),
    );
  }
}

extension _LastOrNull<T> on Iterable<T> {
  T? get lastOrNull {
    final iterator = this.iterator;
    if (!iterator.moveNext()) return null;
    var value = iterator.current;
    while (iterator.moveNext()) {
      value = iterator.current;
    }
    return value;
  }
}
