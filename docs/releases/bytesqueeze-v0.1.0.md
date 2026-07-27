# ByteSqueeze 0.1.0

ByteSqueeze is the Android-first mobile companion for HandBrake TSD Helper. It
remotely manages the Docker-hosted controller and workers; the phone never
performs media encoding.

## Highlights

- Secure one-time pairing with read or control scopes and refreshable tokens.
- Dashboard for live jobs, queue health, library totals, nodes, storage savings,
  Autopilot state, and recent events.
- Poster-first Movies and Shows library with search, show tracking, seasons,
  episodes, library refresh, and remote Smart Preset queueing.
- Active job progress, ETA, queue pause/resume, reordering, cancellation, and
  completed-job history.
- Autopilot observe/manage policies, schedules, capacity limits, readiness
  checks, run-now controls, and explained decisions.
- Smart Preset learning controls that retain English and Spanish audio and
  subtitles, prefer stream copy, and offer surround-preserving E-AC3 or AC-3
  fallback strategies.
- Node, storage, event, connection, and device-security views.
- Responsive Flutter interface with an iOS target and complete iOS icon set.

## Installation

Download `ByteSqueeze-0.1.0+1.apk` from the assets below and sideload it on an
Android 7.0 or newer device. This first APK is debug-signed for local testing;
Google Play distribution will use a private upload key.

Update the HandBrake TSD Helper controller to this release before pairing. In
the web dashboard, open **Settings → Automation & Apps**, generate a one-time
ByteSqueeze code, and enter the controller URL and code in the app.

LAN HTTP is supported for home networks. Use HTTPS through a trusted reverse
proxy outside the home and do not expose the controller directly to the public
internet.

## Verification

- Flutter analyzer: no issues
- Flutter widget tests: passed
- Backend API and pairing regression tests: 10 passed
- Responsive visual QA: pairing, dashboard, library, details, jobs, automation,
  bilingual audio strategy, and server health views passed with no browser errors

APK SHA-256:
`32A886CFDC4DF1DC062243F1386462A2DE21C935319B32BC28FEE5B23F7713CE`
