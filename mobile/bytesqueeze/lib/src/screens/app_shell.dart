import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../theme.dart';
import 'calendar_screen.dart';
import 'dashboard_screen.dart';
import 'jobs_screen.dart';
import 'library_screen.dart';
import 'server_screen.dart';

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
        icon: Icon(Icons.calendar_month_outlined),
        selectedIcon: Icon(Icons.calendar_month_rounded),
        label: 'Calendar'),
    NavigationDestination(
        icon: Icon(Icons.motion_photos_on_outlined),
        selectedIcon: Icon(Icons.motion_photos_on_rounded),
        label: 'Jobs'),
    NavigationDestination(
        icon: Icon(Icons.dns_outlined),
        selectedIcon: Icon(Icons.dns_rounded),
        label: 'Server'),
  ];

  @override
  Widget build(BuildContext context) {
    final pages = [
      DashboardScreen(controller: controller),
      LibraryScreen(controller: controller),
      CalendarScreen(controller: controller),
      JobsScreen(controller: controller),
      ServerScreen(controller: controller),
    ];
    final width = MediaQuery.sizeOf(context).width;
    final wide = width >= 880;
    return Scaffold(
      extendBody: !wide,
      body: DecoratedBox(
        decoration: const BoxDecoration(gradient: ByteSqueezeColors.backdrop),
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
      ),
      bottomNavigationBar: wide
          ? null
          : SafeArea(
              minimum: const EdgeInsets.fromLTRB(12, 0, 12, 10),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(26),
                child: NavigationBar(
                  selectedIndex: controller.selectedTab,
                  onDestinationSelected: controller.selectTab,
                  destinations: _destinations,
                ),
              ),
            ),
    );
  }
}
