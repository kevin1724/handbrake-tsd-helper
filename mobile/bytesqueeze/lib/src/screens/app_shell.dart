import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../theme.dart';
import '../widgets/common.dart';
import 'automation_screen.dart';
import 'dashboard_screen.dart';
import 'jobs_screen.dart';
import 'library_screen.dart';
import 'more_screen.dart';

class AppShell extends StatelessWidget {
  const AppShell({super.key, required this.controller});

  final AppController controller;

  static const _destinations = [
    NavigationDestination(
        icon: Icon(Icons.space_dashboard_outlined),
        selectedIcon: Icon(Icons.space_dashboard_rounded),
        label: 'Home'),
    NavigationDestination(
        icon: Icon(Icons.video_library_outlined),
        selectedIcon: Icon(Icons.video_library_rounded),
        label: 'Library'),
    NavigationDestination(
        icon: Icon(Icons.motion_photos_on_outlined),
        selectedIcon: Icon(Icons.motion_photos_on_rounded),
        label: 'Jobs'),
    NavigationDestination(
        icon: Icon(Icons.auto_awesome_outlined),
        selectedIcon: Icon(Icons.auto_awesome_rounded),
        label: 'Automation'),
    NavigationDestination(
        icon: Icon(Icons.more_horiz_rounded),
        selectedIcon: Icon(Icons.apps_rounded),
        label: 'More'),
  ];

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
    return Scaffold(
      extendBody: !wide,
      appBar: AppBar(
        toolbarHeight: 68,
        titleSpacing: wide ? 24 : 16,
        title: const BrandMark(),
        actions: [
          if (controller.demoMode)
            const Padding(
              padding: EdgeInsets.only(right: 8),
              child: StatusPill(
                  label: 'Demo',
                  color: ByteSqueezeColors.amber,
                  icon: Icons.auto_awesome_rounded),
            ),
          if (!controller.demoMode && width >= 520)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: StatusPill(
                  label: controller.session?.canControl == true
                      ? 'Control access'
                      : 'Read only',
                  color: controller.canControl
                      ? ByteSqueezeColors.mint
                      : ByteSqueezeColors.amber,
                  icon: controller.canControl
                      ? Icons.shield_rounded
                      : Icons.visibility_outlined),
            ),
          IconButton(
            tooltip: 'Refresh everything',
            onPressed: controller.busy ? null : controller.refreshAll,
            icon: controller.busy
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.refresh_rounded),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: DecoratedBox(
        decoration: const BoxDecoration(gradient: ByteSqueezeColors.backdrop),
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
                          leading: const SizedBox(height: 12),
                          destinations: _destinations
                              .map((destination) => NavigationRailDestination(
                                    icon: destination.icon,
                                    selectedIcon: destination.selectedIcon,
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
      bottomNavigationBar: wide
          ? null
          : NavigationBar(
              selectedIndex: controller.selectedTab,
              onDestinationSelected: controller.selectTab,
              destinations: _destinations,
            ),
    );
  }
}
