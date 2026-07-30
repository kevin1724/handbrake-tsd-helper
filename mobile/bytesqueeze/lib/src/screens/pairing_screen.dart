import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../app_controller.dart';
import '../theme.dart';
import '../widgets/common.dart';

class PairingScreen extends StatefulWidget {
  const PairingScreen({super.key, required this.controller});

  final AppController controller;

  @override
  State<PairingScreen> createState() => _PairingScreenState();
}

class _PairingScreenState extends State<PairingScreen> {
  final _formKey = GlobalKey<FormState>();
  final _server = TextEditingController(text: 'http://');
  final _fallbackServer = TextEditingController();
  final _code = TextEditingController();
  final _name = TextEditingController(text: 'ByteSqueeze phone');
  bool _showAdvanced = false;

  @override
  void dispose() {
    _server.dispose();
    _fallbackServer.dispose();
    _code.dispose();
    _name.dispose();
    super.dispose();
  }

  Future<void> _pair() async {
    if (!_formKey.currentState!.validate()) return;
    try {
      await widget.controller.pair(
        baseUrl: _server.text,
        fallbackBaseUrl: _fallbackServer.text,
        code: _code.text,
        deviceName: _name.text,
      );
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(widget.controller.error ?? 'Pairing failed.')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: DecoratedBox(
        decoration: const BoxDecoration(gradient: ByteSqueezeColors.backdrop),
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 30),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 520),
                child: Form(
                  key: _formKey,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Align(
                        child: Hero(
                          tag: 'bytesqueeze-icon',
                          child: ClipRRect(
                            borderRadius: BorderRadius.circular(38),
                            child: Image.asset(
                              'assets/branding/bytesqueeze_icon.png',
                              width: 150,
                              height: 150,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(height: 24),
                      Text('Your TSD control center, in your pocket.',
                          style: Theme.of(context).textTheme.headlineLarge,
                          textAlign: TextAlign.center),
                      const SizedBox(height: 10),
                      const Text(
                        'ByteSqueeze manages the server that does the heavy work. Your phone only monitors and controls it.',
                        style: TextStyle(
                            color: ByteSqueezeColors.muted, fontSize: 16),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 28),
                      SurfaceCard(
                        padding: const EdgeInsets.all(20),
                        gradient: const LinearGradient(
                          begin: Alignment.topLeft,
                          end: Alignment.bottomRight,
                          colors: [Color(0xFF102B57), Color(0xFF0B1832)],
                        ),
                        borderColor: const Color(0xFF24548B),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            Row(
                              children: [
                                const DecoratedBox(
                                  decoration: BoxDecoration(
                                      color: Color(0x2231D6FF),
                                      shape: BoxShape.circle),
                                  child: Padding(
                                    padding: EdgeInsets.all(10),
                                    child: Icon(Icons.link_rounded,
                                        color: ByteSqueezeColors.cyan),
                                  ),
                                ),
                                const SizedBox(width: 12),
                                Expanded(
                                    child: Text('Pair with TSD',
                                        style: Theme.of(context)
                                            .textTheme
                                            .titleLarge)),
                                const StatusPill(
                                    label: 'Secure',
                                    color: ByteSqueezeColors.mint,
                                    icon: Icons.lock_outline_rounded),
                              ],
                            ),
                            const SizedBox(height: 20),
                            TextFormField(
                              controller: _server,
                              keyboardType: TextInputType.url,
                              autocorrect: false,
                              textInputAction: TextInputAction.next,
                              decoration: const InputDecoration(
                                labelText: 'TSD server address',
                                hintText: 'http://192.168.1.50:8080',
                                prefixIcon: Icon(Icons.dns_outlined),
                              ),
                              validator: (value) =>
                                  (value ?? '').trim().length < 4
                                      ? 'Enter the server address.'
                                      : null,
                            ),
                            const SizedBox(height: 12),
                            TextFormField(
                              controller: _code,
                              textCapitalization: TextCapitalization.characters,
                              autocorrect: false,
                              inputFormatters: [
                                FilteringTextInputFormatter.allow(
                                    RegExp('[a-zA-Z0-9-]')),
                                LengthLimitingTextInputFormatter(9),
                              ],
                              decoration: const InputDecoration(
                                labelText: 'One-time pairing code',
                                hintText: 'ABCD-EFGH',
                                prefixIcon: Icon(Icons.password_rounded),
                              ),
                              validator: (value) =>
                                  (value ?? '').replaceAll('-', '').length != 8
                                      ? 'Enter the eight-character code.'
                                      : null,
                              onFieldSubmitted: (_) => _pair(),
                            ),
                            const SizedBox(height: 8),
                            TextButton.icon(
                              onPressed: () => setState(
                                  () => _showAdvanced = !_showAdvanced),
                              icon: Icon(_showAdvanced
                                  ? Icons.expand_less
                                  : Icons.tune_rounded),
                              label: Text(_showAdvanced
                                  ? 'Hide connection options'
                                  : 'Connection options'),
                            ),
                            AnimatedSize(
                              duration: const Duration(milliseconds: 220),
                              child: _showAdvanced
                                  ? Padding(
                                      padding:
                                          const EdgeInsets.only(bottom: 12),
                                      child: Column(
                                        children: [
                                          TextFormField(
                                            controller: _fallbackServer,
                                            keyboardType: TextInputType.url,
                                            autocorrect: false,
                                            decoration: const InputDecoration(
                                              labelText:
                                                  'Away / Tailscale address (optional)',
                                              hintText: 'http://100.x.x.x:8080',
                                              prefixIcon:
                                                  Icon(Icons.route_rounded),
                                              helperText:
                                                  'Used automatically when the home address cannot be reached.',
                                            ),
                                          ),
                                          const SizedBox(height: 12),
                                          TextFormField(
                                            controller: _name,
                                            decoration: const InputDecoration(
                                                labelText: 'Device name',
                                                prefixIcon: Icon(Icons
                                                    .phone_android_rounded)),
                                          ),
                                        ],
                                      ),
                                    )
                                  : const SizedBox.shrink(),
                            ),
                            FilledButton.icon(
                              onPressed: widget.controller.busy ? null : _pair,
                              icon: widget.controller.busy
                                  ? const SizedBox(
                                      width: 18,
                                      height: 18,
                                      child: CircularProgressIndicator(
                                          strokeWidth: 2))
                                  : const Icon(Icons.link_rounded),
                              label: Text(widget.controller.busy
                                  ? 'Pairing…'
                                  : 'Connect ByteSqueeze'),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 16),
                      OutlinedButton.icon(
                        onPressed: widget.controller.busy
                            ? null
                            : widget.controller.enterDemo,
                        icon: const Icon(Icons.auto_awesome_rounded),
                        label: const Text('Explore the demo dashboard'),
                        style: OutlinedButton.styleFrom(
                          padding: const EdgeInsets.symmetric(vertical: 15),
                          side: const BorderSide(color: ByteSqueezeColors.line),
                          shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(16)),
                        ),
                      ),
                      const SizedBox(height: 22),
                      const Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Icon(Icons.info_outline_rounded,
                              size: 18, color: ByteSqueezeColors.muted),
                          SizedBox(width: 9),
                          Expanded(
                            child: Text(
                              'Generate the code in TSD Settings > Linked Nodes, under Companion app access. A Tailscale address can be saved as the automatic away-from-home fallback.',
                              style: TextStyle(
                                  color: ByteSqueezeColors.muted,
                                  fontSize: 12.5,
                                  height: 1.4),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
