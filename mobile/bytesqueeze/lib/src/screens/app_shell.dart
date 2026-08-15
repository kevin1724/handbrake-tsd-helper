import 'dart:async';

import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../theme.dart';
import '../widgets/common.dart';
import 'automation_screen.dart';
import 'dashboard_screen.dart';
import 'jobs_screen.dart';
import 'library_screen.dart';
import 'more_screen.dart';

class AppShell extends StatefulWidget {
  const AppShell({super.key, required this.controller});

  final AppController controller;

  static const _destinations = [
    NavigationDestination(
        icon: Icon(Icons.space_dashboard_outlined),
        selectedIcon: Icon(Icons.space_dashboard_rounded),
        label: 'Overview'),
    NavigationDestination(
        icon: Icon(Icons.video_library_outlined),
        selectedIcon: Icon(Icons.video_library_rounded),
        label: 'Library'),
    NavigationDestination(
        icon: Icon(Icons.motion_photos_on_outlined),
        selectedIcon: Icon(Icons.motion_photos_on_rounded),
        label: 'Queue'),
    NavigationDestination(
        icon: Icon(Icons.auto_awesome_outlined),
        selectedIcon: Icon(Icons.auto_awesome_rounded),
        label: 'Automate'),
    NavigationDestination(
        icon: Icon(Icons.more_horiz_rounded),
        selectedIcon: Icon(Icons.apps_rounded),
        label: 'More'),
  ];

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  Timer? _operationsTimer;
  bool _polling = false;

  AppController get controller => widget.controller;

  @override
  void initState() {
    super.initState();
    if (!controller.demoMode) {
      _operationsTimer = Timer.periodic(
        const Duration(seconds: 15),
        (_) => _refreshOperations(),
      );
    }
  }

  @override
  void dispose() {
    _operationsTimer?.cancel();
    super.dispose();
  }

  Future<void> _refreshOperations() async {
    if (_polling ||
        controller.busy ||
        controller.demoMode ||
        controller.session == null) {
      return;
    }
    _polling = true;
    try {
      await controller.refreshJobsAndDashboard();
    } catch (_) {
      // The global banner handles connection errors from a full refresh. A
      // transient background poll should not interrupt the current screen.
    } finally {
      _polling = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final pages = [
      DashboardScreen(controller: controller),
      LibraryScreen(controller: controller),
      JobsScreen(controller: controller),
      AutomationScreen(controller: controller),
      MoreScreen(controller: controller),
    ];
    final width = MediaQuery.sizeOf(context).width;
    final wide = width >= 880;
    final queue = asMap(controller.dashboard['queue']);
    final summary = asMap(queue['summary']);
    final activeJobs = asList(controller.dashboard['active_jobs']);
    return Scaffold(
      extendBody: !wide,
      body: Stack(
        children: [
          Positioned.fill(
            child: DecoratedBox(
              decoration:
                  const BoxDecoration(gradient: ByteSqueezeColors.backdrop),
              child: SafeArea(
                bottom: false,
                child: Column(
                  children: [
                    if (controller.error != null)
                      MaterialBanner(
                        backgroundColor:
                            ByteSqueezeColors.danger.withValues(alpha: .10),
                        leading: const Icon(Icons.cloud_off_rounded,
                            color: ByteSqueezeColors.danger),
                        content: Text(controller.error!),
                        actions: [
                          TextButton(
                              onPressed: controller.refreshAll,
                              child: const Text('Retry'))
                        ],
                      ),
                    Expanded(
                      child: wide
                          ? Row(
                              children: [
                                NavigationRail(
                                  selectedIndex: controller.selectedTab,
                                  onDestinationSelected: controller.selectTab,
                                  labelType: NavigationRailLabelType.all,
                                  leading: const Padding(
                                    padding: EdgeInsets.only(bottom: 18),
                                    child:
                                        BrandMark(size: 42, showName: false),
                                  ),
                                  destinations: AppShell._destinations
                                      .map((destination) =>
                                          NavigationRailDestination(
                                            icon: destination.icon,
                                            selectedIcon:
                                                destination.selectedIcon,
                                            label: Text(destination.label),
                                          ))
                                      .toList(),
                                ),
                                const VerticalDivider(width: 1),
                                Expanded(
                                    child: IndexedStack(
                                        index: controller.selectedTab,
                                        children: pages)),
                              ],
                            )
                          : IndexedStack(
                              index: controller.selectedTab, children: pages),
                    ),
                  ],
                ),
              ),
            ),
          ),
          Positioned(
            left: wide ? 112 : 12,
            right: wide ? 24 : 12,
            bottom: wide ? 14 : 88 + MediaQuery.paddingOf(context).bottom,
            child: Align(
              alignment: Alignment.bottomCenter,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 720),
                child: OperationsDock(
                  summary: summary,
                  activeJobs: activeJobs,
                  paused: queue['paused'] == true,
                  onTap: () => controller.selectTab(2),
                ),
              ),
            ),
          ),
        ],
      ),
      bottomNavigationBar: wide
          ? null
          : SafeArea(
              minimum: const EdgeInsets.fromLTRB(12, 0, 12, 10),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(19),
                child: NavigationBar(
                  selectedIndex: controller.selectedTab,
                  onDestinationSelected: controller.selectTab,
                  destinations: AppShell._destinations,
                ),
              ),
            ),
    );
  }
}
