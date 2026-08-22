# ByteSqueeze 0.9.0

ByteSqueeze 0.9.0 makes complete-show and season Smart Queues genuinely episode-aware.

- Every episode is independently probed and receives an immutable Smart Preset snapshot.
- HDR transfer, primaries, bit depth, codec, resolution, duration, and frame rate are detected from the actual stream instead of another episode or filename alone.
- A codec-aware minimum quality floor prevents tight season targets from starving 4K HDR episodes.
- Supported HDR dynamic metadata is explicitly preserved, and HDR10+/Dolby Vision avoids incompatible hardware encoder paths.
- The new opt-in beta scene-analysis control can send 3–8 representative JPEG stills per episode to the configured OpenAI or Gemini provider.
- AI scene hints are bounded to a small bitrate adjustment and fall back to deterministic planning on every failure path.
- Mobile Library wording now makes clear that a season preview samples one episode while queued plans remain independent for every episode.

This mobile release pairs with controller 3.17.0 and worker 2.7.0.
