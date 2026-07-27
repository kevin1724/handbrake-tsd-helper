import 'dart:async';

import 'package:flutter/material.dart';

import 'src/app_controller.dart';
import 'src/screens/app_shell.dart';
import 'src/screens/pairing_screen.dart';
import 'src/theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final controller = AppController();
  runApp(ByteSqueezeApp(controller: controller));
  unawaited(controller.bootstrap());
}

class ByteSqueezeApp extends StatelessWidget {
  const ByteSqueezeApp({super.key, required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: controller,
      builder: (context, _) {
        return MaterialApp(
          title: 'ByteSqueeze',
          debugShowCheckedModeBanner: false,
          theme: ByteSqueezeTheme.dark,
          home: AnimatedSwitcher(
            duration: const Duration(milliseconds: 360),
            child: controller.booting
                ? const _LaunchScreen(key: ValueKey('launch'))
                : controller.connected
                    ? AppShell(
                        key: const ValueKey('shell'), controller: controller)
                    : PairingScreen(
                        key: const ValueKey('pair'), controller: controller),
          ),
        );
      },
    );
  }
}

class _LaunchScreen extends StatelessWidget {
  const _LaunchScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: DecoratedBox(
        decoration: const BoxDecoration(gradient: ByteSqueezeColors.backdrop),
        child: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(36),
                child: Image.asset(
                  'assets/branding/bytesqueeze_icon.png',
                  width: 132,
                  height: 132,
                ),
              ),
              const SizedBox(height: 22),
              Text('ByteSqueeze',
                  style: Theme.of(context).textTheme.headlineMedium),
              const SizedBox(height: 18),
              const SizedBox(
                width: 28,
                height: 28,
                child: CircularProgressIndicator(strokeWidth: 2.5),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
