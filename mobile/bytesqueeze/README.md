# ByteSqueeze

ByteSqueeze is the Flutter remote-control app for HandBrake TSD Helper.

- Android first, with the iOS target maintained from day one
- Secure one-time pairing and refreshable bearer sessions
- Dashboard, library posters, shows and episodes, jobs, Autopilot, Smart
  Presets, nodes, storage history, and events
- All transcoding remains on the Docker-hosted TSD controller and workers

## Run

```bash
flutter pub get
dart run flutter_launcher_icons
flutter run
```

The pairing code is generated in the TSD web dashboard under **Settings →
Automation & Apps**. LAN HTTP is enabled on Android for home-server setups;
use a trusted HTTPS reverse proxy for remote access.

## Android package

`com.kevina1724.bytesqueeze`

The current release build uses debug signing for local APK testing. Configure a
private upload keystore before publishing to Google Play.

Local release builds are written to `dist/` for installation testing. APK files
are intentionally ignored by Git; publish signed binaries through a release or
app-store workflow rather than committing them to the source tree.

## iOS

The shared Flutter UI, API client, secure session store, responsive navigation,
and application state are already used by `ios/`. A release port needs Apple
signing, bundle registration, App Store metadata, and physical-device testing.
