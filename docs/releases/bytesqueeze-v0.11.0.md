# ByteSqueeze 0.11.0

ByteSqueeze 0.11.0 starts the universal Apple release while preserving the complete Android experience.

## iPhone and iPad

- The same Size Wizard, Smart Presets, library, combined queue, linked-node controls, Autopilot, and settings run on iPhone and iPad.
- iPad automatically uses the wide ByteSqueeze workspace and supports every orientation, Split View, keyboards, and pointer input.
- Local-controller access has a clear iOS local-network permission and a narrow App Transport Security exception for LAN addresses.
- The native Apple launch screen now matches the dark ByteSqueeze interface.
- App Store privacy and exempt-encryption metadata are included in the app bundle.

## Build and testing

- A macOS GitHub Actions job compiles an unsigned physical-device release after relevant pushes and verifies that the resulting app targets both iPhone and iPad.
- A separate manual workflow imports Apple signing credentials, downloads the matching profile, builds the signed IPA, and uploads it to TestFlight.
- A tablet widget test protects the full iPad navigation and Library workspace.

TestFlight publishing stays disabled until the repository owner configures Apple Developer and App Store Connect credentials. See [`../ios-testflight.md`](../ios-testflight.md).
