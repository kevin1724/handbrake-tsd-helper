# ByteSqueeze Mobile

ByteSqueeze is the cross-platform remote control for HandBrake TSD Helper. The
phone never transcodes media. It pairs with the Docker-hosted controller and
uses the versioned mobile API to inspect the library, manage the queue and
jobs, tune automation, and watch node and storage health.

## Product direction

- Android ships first from a Flutter codebase.
- The same Dart UI, state, and API layers are used by the generated iOS target.
- The visual language is original to ByteSqueeze: deep navy surfaces, electric
  blue/cyan status accents, soft elevated cards, large poster art, and compact
  operational controls.
- Media-manager apps such as nzb360 informed the information hierarchy—one
  dashboard, fast service switching, poster-rich libraries, and controls close
  to live status—but ByteSqueeze does not copy its layouts, assets, or branding.

## Main areas

1. **Home** — queue health, active work, Autopilot, nodes, library totals,
   reclaimed storage, and recent events.
2. **Library** — searchable Movies and Shows poster rails, a complete catalog,
   show monitoring, seasons/episodes, and node-aware Smart Preset queueing.
3. **Jobs** — active progress and ETA, queue pause/resume, reordering,
   cancellation, and history.
4. **Autopilot** — first-run and restartable tours, accurate preview training,
   policy guardrails, decision explanations, and after-watch feedback.
5. **More** — upcoming-episode calendar, worker, storage, event, and connection
   controls.

Wide screens use a navigation rail while phones use bottom navigation. This
keeps tablets and a future iPad build useful without creating a second UI.

## Pairing

1. Open **Settings > Linked Nodes** in the TSD web dashboard and find **Companion app access**.
2. Generate a ByteSqueeze pairing code with read or control scope.
3. Enter the controller URL and one-time code in ByteSqueeze.
4. The access and refresh tokens are stored with platform secure storage.

LAN HTTP is supported for home networks. HTTPS through a trusted reverse proxy
is recommended for access outside the home. Do not expose the controller
directly to the public internet.

## Development

The Flutter project lives in `mobile/bytesqueeze`.

```bash
cd mobile/bytesqueeze
flutter pub get
flutter test
flutter run
```

Create a release APK with:

```bash
flutter build apk --release
```

The first Android release uses package id `com.kevina1724.bytesqueeze`.

## iOS port

The generated `ios/` target and complete AppIcon set are kept in the repository.
Port work is limited to Apple signing, bundle registration and metadata, and
physical-device testing. Networking, secure session storage, screens,
responsive navigation, and business logic are shared with Android.

## Mobile API v1

ByteSqueeze uses bearer-authenticated routes under `/api/mobile/v1`:

- discovery, pairing, and token refresh
- dashboard and server status
- jobs, queue state, job actions, and history cleanup
- poster-rich library cache, refresh, queueing, and show tracking
- release calendar and TMDb-first/keyless-fallback metadata attribution
- explicit local, best-worker, or selected-worker queue targets
- Autopilot onboarding, preview training, after-watch feedback, policy updates, and run-now
- Smart Preset profile and learning state
- nodes, storage statistics, and events

Read-scoped devices cannot call control routes. Tokens are returned only to the
mobile client; the server persists hashes rather than plaintext credentials.
