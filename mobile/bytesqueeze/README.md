# ByteSqueeze

ByteSqueeze is the Flutter remote-control app for HandBrake TSD Helper.

- Android first, with the iOS target maintained from day one
- Secure one-time pairing and refreshable bearer sessions
- V3 Beta adaptive workspace with a desktop sidebar, polished phone dock, and
  global command center
- Persistent V2 Classic fallback and comfortable/compact density controls in
  **Settings → Interface & layout**
- Persistent live operations dock with automatic queue/progress refresh
- Running-now, up-next, and history queue views with GPU-capacity guidance
- Mobile control of safe GPU concurrency and projected-output-size protection;
  CPU/software encoding always remains exclusive
- Graceful compatibility with older TSD servers: unsupported V3 controls become
  read-only without falsely reporting that the entire server connection failed
- Complete movie/show catalog, TMDb-first artwork with no-key fallback, upcoming episode calendar,
  friendly savings/HDR/tracked filters, movie and season Smart Queue guardrails,
  real Library comparison previews, guided Autopilot preview training, preservation-first Smart Presets,
  storage, and events
- Automatic switching between a primary home URL and optional Tailscale/away URL
- All transcoding remains on the Docker-hosted TSD controller and workers

## Run

```bash
flutter pub get
dart run flutter_launcher_icons
flutter run
```

The pairing code is generated in the TSD web dashboard under **Settings >
Linked Nodes**, in **Companion app access**. Pair with the home URL and optionally save a Tailscale URL;
ByteSqueeze automatically tries the other address when the current route cannot
connect. LAN HTTP is enabled on Android for home-server setups.

Autopilot is a first-class page in the main navigation. Its first-run tour,
restartable guide, preview training, guardrails, decision history, and
after-watch feedback use the same learning profile as the web dashboard. Generate a short
accurate preview, compare the original and proposed frames, then approve it or
choose what needs improvement. Reviews made on the phone and web dashboard feed
the same local Smart Preset profile.

V3 adds a command center for navigation, refresh, queue pause/resume, library
scans, and Smart Queue entry. Open it from the search button, or with `Ctrl/Cmd+K`
or `/` when ByteSqueeze is running on a keyboard-equipped device. The interface
choice is stored only on that device; changing between V3 Beta and V2 Classic
never changes server settings or media data.

Smart Preset protections are editable from both **Settings → Smart Presets** on the web and the
phone. They can lock source resolution, black bars, display aspect ratio, every
audio/subtitle language, and audio passthrough across full-season queues.

## Android package

`com.kevina1724.bytesqueeze`

The current release build uses debug signing for local APK testing. Configure a
private upload keystore before publishing to Google Play.

Local release builds are written to `dist/` for installation testing. APK files
are intentionally ignored by Git; publish signed binaries through a release or
app-store workflow rather than committing them to the source tree.

Pushing a `bytesqueeze-v*` tag, or manually running the **Publish ByteSqueeze
Android** GitHub workflow with a release tag, runs analysis and tests, builds the
release APK, creates its SHA-256 checksum, and attaches both files to the GitHub
release. Versions containing a prerelease suffix such as `-beta.1` are published
as GitHub prereleases and do not replace the latest stable download.

## iOS

The shared Flutter UI, API client, secure session store, responsive navigation,
and application state are already used by `ios/`. A release port needs Apple
signing, bundle registration, App Store metadata, and physical-device testing.
