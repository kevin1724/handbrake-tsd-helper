# Autopilot guide

Autopilot is the guarded, explainable automation layer in HandBrake TSD Helper. It discovers media inside folders you explicitly map, predicts whether an encode is worthwhile, chooses a learned Smart Preset, and can add a bounded amount of work to the queue.

Open **Autopilot** in the main navigation, or visit `/autopilot`. Setup, preview training, policy limits, decision explanations, and post-encode feedback all live on that page.

## Recommended first-time setup

1. Open **Settings > Library** and map the exact Movies and Shows folders the controller may scan.
2. Refresh the Library so Autopilot has real files to evaluate.
3. Open **Autopilot** and follow the guided tour.
4. In **Initial training**, select **Create first preview**. Autopilot chooses a representative unencoded file and creates only a short comparison clip.
5. Watch the side-by-side clip and inspect the original and proposed frames.
6. Select **Looks good** only if you would be happy watching the full movie or episode at that quality. Otherwise choose what is wrong and select **Needs changes**.
7. Review at least two useful samples. Learned selection unlocks only after enough consistent approvals; the page always shows the remaining count.
8. Load the **Safe starter** or **Balanced** policy and save it in Observe mode.
9. Run a decision cycle. Read the eligible, waiting, and skipped reasons. Observe never adds a job.
10. After the decisions match your expectations and every required readiness check passes, switch to Manage and save.

You can close the page while a preview is encoding and return later. Preview state and learning history are shared with paired ByteSqueeze clients.

## Using Autopilot from ByteSqueeze

ByteSqueeze 0.3.12 places **Autopilot** directly in the main phone navigation rather than hiding it under Server. The first visit opens the same five-step guided setup used by the website. You can restart the tour or open the complete in-app guide at any time.

Preview training, readiness, policy limits, explained decisions, and after-watch feedback are shared with the controller. Calendar, nodes, storage, events, and connection settings are under **More**, keeping the phone navigation focused on Home, Library, Jobs, and Autopilot.

## Observe and Manage

**Observe** scans and explains. It never changes the queue. Use it while tuning the minimum source size, minimum predicted savings, schedule, and capacity.

**Manage** can add eligible jobs, but it is still constrained by:

- mapped-folder boundaries;
- the new-file stability window;
- movie and TV inclusion choices;
- minimum source size and predicted savings;
- schedule start and end;
- maximum jobs added per scan;
- maximum active queue jobs;
- learned-preset readiness;
- the existing oversized-output guard, encode validation, and source-file protection.

Manage does not remove these checks and cannot queue a file that is outside the allowed roots or still being copied.

## What preview training teaches

Every review stores a small, local preference record in `data/smart_presets.json`. It contains source and plan characteristics, not video frames. Similarity considers:

- movie or TV source type;
- HDR state and resolution class;
- codec and encoder family;
- output resolution;
- target-size ratio;
- whether you approved the choice or rejected it for quality, size, speed, or compatibility.

The deterministic Size Wizard remains responsible for legal and safe HandBrake arguments. Learning ranks safe candidates; it does not generate arbitrary command-line arguments.

## Feedback after watching a completed encode

A short preview cannot reveal every problem. When a learned Smart Preset job finishes, it appears under **How did completed encodes actually look?** on the Autopilot page.

- Choose **Looked and sounded good** when the completed media meets your expectations.
- Choose **Report a problem** and identify picture quality, playback compatibility, audio, subtitles, output size, or another issue when it does not.

This feedback is saved with a `post_encode` origin and influences later recommendations for similar sources. It does not retry, delete, or replace the completed file automatically. Feedback can be submitted only once per completed job so accidental duplicate taps do not distort learning.

Turn off **Ask for feedback after encodes** in the Autopilot policy if you do not want ongoing review prompts. Existing learning remains available.

## Audio and subtitles

Smart Presets use the preservation rules saved in **Settings → Smart Presets**. By default they keep every audio and subtitle language, pass audio through without transcoding, retain source resolution and aspect ratio, and disable automatic cropping so black bars remain intact. You can turn off an individual protection and use an explicit language list or E-AC3 5.1 when that tradeoff is intentional. A post-encode audio or subtitle rejection teaches candidate selection that the chosen track strategy was unacceptable for a similar source.

## Decision meanings

- **Eligible:** the file passed the current policy and safety checks.
- **Waiting:** the file may become eligible, but it is still inside the write-stability window or another temporary condition applies.
- **Skipped:** a policy or safety rule excludes the file. The displayed reason identifies which rule.
- **Error:** planning failed and the item was not queued.

## AI advisor and Autopilot learning are different

The optional Gemini, OpenAI, or local Size Wizard advisor explains a single wizard plan and can suggest validated setting changes. Autopilot learning uses your own preview and playback feedback stored locally. Cloud AI is not required for Autopilot.

Configure the optional advisor under **Settings > AI & API Keys**. API keys stay on the controller. Only compact probe facts, chosen options, and your typed question are sent to the selected provider; media contents are not uploaded. See the [AI Advisor setup guide](AI_ADVISOR.md) for provider walkthroughs and examples.

## Troubleshooting

### No training sample is available

Map at least one Movies or Shows folder, refresh the Library, and confirm it contains an unencoded video file inside an allowed root. Files already ending in `-TSD` are intentionally ignored.

### The preview takes a long time

Accurate Preview runs a short real HandBrake encode. Software encoding may be slower than QSV, especially for 4K or AV1 sources. You can leave the page and return while it runs.

### Manage will not unlock

Read the readiness checks at the top of the Autopilot page. Required checks are mapped folders, writable durable data, an available HandBrake preset, and sufficient consistent preview training. Optional hardware and worker warnings do not prevent standalone use.

### A completed job is not asking for feedback

Post-encode feedback is available only for completed jobs created with a learned Smart Preset by Autopilot or the Smart Preset queue path. Manually configured jobs do not have the required learning context.

### Autopilot queued something unexpected

Switch the policy back to Observe, run a new cycle, and inspect the decision reason. Adjust policy limits or submit playback feedback for a completed learned job before returning to Manage.
