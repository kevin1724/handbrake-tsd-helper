import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../theme.dart';
import 'automation_screen.dart';
import 'more_screen.dart';

class ServerScreen extends StatefulWidget {
  const ServerScreen({super.key, required this.controller});

  final AppController controller;

  @override
  State<ServerScreen> createState() => _ServerScreenState();
}

class _ServerScreenState extends State<ServerScreen> {
  bool _autopilot = false;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        SafeArea(
          bottom: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 8, 20, 0),
            child: SegmentedButton<bool>(
              segments: const [
                ButtonSegment(
                    value: false,
                    icon: Icon(Icons.dns_outlined),
                    label: Text('Server')),
                ButtonSegment(
                    value: true,
                    icon: Icon(Icons.auto_awesome_outlined),
                    label: Text('Autopilot')),
              ],
              selected: {_autopilot},
              showSelectedIcon: false,
              onSelectionChanged: (values) =>
                  setState(() => _autopilot = values.first),
              style: const ButtonStyle(
                backgroundColor:
                    WidgetStatePropertyAll(ByteSqueezeColors.surface),
              ),
            ),
          ),
        ),
        Expanded(
          child: IndexedStack(
            index: _autopilot ? 1 : 0,
            children: [
              MoreScreen(controller: widget.controller),
              AutomationScreen(controller: widget.controller),
            ],
          ),
        ),
      ],
    );
  }
}
