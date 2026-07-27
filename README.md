# HandBrake TSD Helper

A clean, self-hosted web dashboard for managing HandBrake encodes across a movie and TV library.

HandBrake TSD Helper is built for Plex, Jellyfin, Emby, NAS, and homelab users who want to reduce media file sizes without giving up control over quality, audio, subtitles, presets, hardware encoding, or file safety.

Completed output files are tagged with `-TSD`, short for "Transcoded", so the app can skip media that has already been processed.

[![Docker Pulls](https://img.shields.io/docker/pulls/kevina1724/handbrake-tsd-helper?style=for-the-badge&logo=docker)](https://hub.docker.com/r/kevina1724/handbrake-tsd-helper)

## Highlights

- Web dashboard for local and remote HandBrake encoding
- Modern dark UI for Jobs, Size Wizard, Library, and Settings
- One-shot encoder, batch tools, queue history, and live progress
- Size Wizard with Simple Mode, Advanced Mode, previews, and AI-assisted recommendations
- Library scanner for mapped movie and show folders
- Poster view, show tracking, seasons, episodes, and recommendation sorting
- Storage-savings history with output-size and runtime prediction
- Intel QSV, software encoders, HEVC, H.264, and AV1 planning support
- Multi-node controller/worker encoding
- Remote-transfer mode for workers that do not have media drives mounted
- Bounded Autopilot with observe/manage modes, schedules, queue caps, and explained decisions
- Transactional node protocol v2 with safe pairing retries, automatic session recovery, and diagnostics
- Versioned mobile API foundation with hashed tokens, refresh, scopes, and device revocation
- Safer cleanup behavior for failed or canceled jobs

## Release 2.0 Refresh

The 2.0 control center is designed for set-it-up-and-let-it-run operation without giving automation unlimited control:

- **Observe mode** scans and explains what it would queue without changing the queue.
- **Manage mode** queues only stable, allowed media within the configured schedule, batch limit, and maximum active-job count.
- **Readiness checks** call out missing library mappings, presets, durable storage, hardware acceleration, and worker availability.
- **Decision history** shows why each item was eligible, skipped, or left waiting.
- **Production runtime** uses a single Gunicorn process with threaded HTTP handling so queue and scheduler ownership stays deterministic.

Autopilot is disabled and set to Observe by default. Start with a few manual test encodes so prediction history can learn your presets and hardware.

## Why Use It

HandBrake is powerful, but managing a large library by hand is slow. This project adds a web UI, queue system, history, predictions, library scanning, and worker-node support around HandBrakeCLI.

Use it when you want to:

- Shrink large movies and shows
- Keep track of how much storage you saved
- Queue encodes from a browser
- Avoid re-encoding files that are already done
- Use presets without opening the HandBrake desktop app
- Send jobs to another machine on your network
- Keep original files safe unless an encode fully succeeds

## Quick Start

Clone the repo:

```bash
git clone https://github.com/kevin1724/handbrake-tsd-helper.git
cd handbrake-tsd-helper
```

Edit `docker-compose.yml` and mount your media folders:

```yaml
services:
  hb-web:
    ports:
      - "8081:8080"
    volumes:
      - /path/to/movies:/media/Movies
      - /path/to/shows:/media/Shows
      - ./data:/app/data
      - ./presets:/presets
```

Start the app:

```bash
docker compose up -d --build
```

Open the web UI:

```text
http://SERVER-IP:8081
```

Recommended first setup:

1. Open Settings.
2. Select your CPU profile.
3. Confirm or upload your HandBrake presets.
4. Map movie and show folders.
5. Add TMDb credentials if you want posters.
6. Run a Library scan.
7. Queue a few test encodes.
8. Open **Settings → Automation & Apps**, review readiness, and enable Autopilot in Observe mode.

## Core Pages

### Dashboard

The Dashboard is the main operations and encode view.

- Review Autopilot readiness, schedule, worker capacity, and potential savings
- Run a bounded decision cycle and jump to its policy settings
- Browse folders and video files
- Select a file and encode it with presets
- Open a file in the Size Wizard
- Run batch tools
- View queued, running, completed, and failed jobs
- Track ETA, progress, estimated final size, saved size, and runtime
- Cancel running jobs
- View linked worker-node status

### Size Wizard

The Size Wizard helps choose better settings before starting an encode.

Simple Mode keeps the workflow easy:

- Pick a file
- Choose a quality goal
- Set a target size
- Choose speed or compression preference
- Keep or filter audio and subtitle languages
- Review the live plan
- Queue the encode

Advanced Mode keeps the full technical surface available:

- Codec and encoder
- AV1, HEVC, H.264, software, and QSV choices
- Bit depth
- Frame rate
- Resolution and downscale controls
- Audio tracks
- Subtitle tracks
- Language selection
- Crop, deinterlace, filters, two-pass, and extra args
- Saved wizard presets
- Fast and accurate previews

The wizard also includes AI-assisted recommendations. It can suggest a best overall plan, a best-compression plan, a faster plan, or a 1080p space-saving plan for large 4K files.

Smart Presets add a learning loop on top of that safe planner:

- Choose the main goal, playback compatibility, hardware preference, and audio strategy
- Always retain every matching English and Spanish audio and subtitle track
- Copy original audio bit-for-bit, or save space with E-AC3 5.1 at 640 kbps while retaining surround playback
- Generate three source-aware candidates ranked by quality, savings, speed, compatibility, and prior feedback
- Apply a candidate and inspect the same short HandBrake encode that a real job will use
- Approve the preview or mark quality, size, speed, or compatibility concerns
- Keep all preference history local in `data/smart_presets.json`
- Unlock automatic selection only after the configured minimum number of consistent reviews

The learned model is intentionally explainable. It uses similar source type, HDR state, resolution, codec, encoder family, target ratio, and output resolution to weight past reviews. The deterministic Size Wizard remains authoritative over HandBrake arguments, while the AI planner and optional local model help evaluate and explain the safe choices. When learning is ready, **Smart learned preset** is available from Jobs and Library, and Autopilot Manage mode can choose it automatically.

### Library

The Library page scans the movie and show folders you map in Settings.

- Cached scans
- Movie poster grid
- Show cards with seasons and episodes
- Optional TMDb posters
- Sort by likely storage savings
- Filter by title, quality, type, and status
- Queue movies, episodes, seasons, shows, or selected batches
- Track shows and auto-queue new stable episodes
- Send jobs to local encoding or linked workers

The scanner ignores files that already contain `-TSD`.

### Settings

Settings are split into cleaner sections:

- Encoding defaults
- Preset management
- CPU profile
- Intel QSV availability
- Library folder mapping
- Poster metadata
- Auto scan
- Autopilot policy and decision status
- Companion-app access and device revocation
- Linked nodes
- Events
- Storage savings

Events and storage savings use scrollable tables so the page stays compact.

## File Safety

The app is designed to protect original files.

- Failed jobs delete the incomplete `-TSD` output, not the source file
- Canceled jobs preserve the source file
- Already encoded `-TSD` files are skipped by scans and queues
- Remote-transfer output is verified before being written beside the original
- Original deletion only happens after a successful encode and verification
- Clear actions ask for confirmation

Keep backups of important media before enabling any aggressive cleanup behavior.

## Auto Scan

Auto scan can keep the Library updated without constantly probing every file.

By default, it is designed to run every 30 minutes. On each pass it:

1. Checks whether auto scan is enabled.
2. Skips if an encode is running and skip-while-encoding is enabled.
3. Loads the previous scan index.
4. Walks only mapped movie and show folders.
5. Compares path, size, and modified time.
6. Parses only new or changed video files.
7. Ignores `-TSD` files.
8. Marks missing files as removed.
9. Saves the scan index and Library cache.
10. Auto-queues tracked episodes only after file stability checks pass.

This keeps normal scans lightweight.

## Autopilot

Autopilot reuses the incremental Library index and existing file-safety checks. A decision cycle:

1. Scans only mapped media roots and ignores `-TSD` outputs.
2. Waits for new or changed files to pass the configured stability window.
3. Excludes files already owned by queued or running jobs.
4. Applies movie/show, minimum-size, and predicted-savings policy rules.
5. Sorts eligible work by predicted savings and source size.
6. In Observe mode, records recommendations only.
7. In Manage mode, queues no more than the per-scan limit and never exceeds the active-job cap.

Autopilot does not weaken the existing output verification or original-file protections.

## Multi-Node Encoding

HandBrake TSD Helper can link multiple app containers together.

- One node acts as the controller
- Other nodes act as workers
- Workers pair with one-time codes
- Pairing is idempotently recoverable for the same controller when a network response is lost
- Node state writes are serialized and atomic, with backup recovery
- Protocol discovery negotiates capabilities while remaining compatible with older workers
- Paired nodes use trusted tokens for commands
- Workers report heartbeat, status, progress, completed jobs, and errors
- Nodes can reconnect after normal offline periods
- Prediction history is tracked per worker

The controller can send jobs to the local node, the best available worker, or a selected worker.

Use `GET /api/nodes/diagnostics` to inspect protocol, monitor health, heartbeat failures, and linked-node totals.

## Android Companion API Foundation

Release 2.0 includes the backend contract for a future Android companion app; it does **not** include the Android app itself.

- Discovery: `GET /api/mobile/v1/discovery`
- Pairing: `POST /api/mobile/v1/pair`
- Token rotation: `POST /api/mobile/v1/token/refresh`
- Read endpoints for status, jobs, nodes, and events
- Scoped queue pause/resume for devices granted control permission
- Browser-admin controls for creating pairing codes and revoking devices

Access and refresh tokens are returned only to the client and stored on the server as hashes. Keep the web UI and mobile API on a trusted LAN or behind your own authenticated reverse proxy; the main web UI does not yet provide user accounts.

### Worker Modes

**Local mounted media mode**

Use this when the worker can access the same media through its own mounted paths.

```text
Controller path: /media/Movies
Worker path:     /mnt/media/Movies
```

**Auto local then remote**

Use this when some paths are mounted on the worker and some are not. The app tries path mapping first, then falls back to remote transfer.

**Remote transfer mode**

Use this when the worker cannot access the media drive.

1. The controller grants temporary authenticated file access.
2. The worker downloads the source file to local temp storage.
3. The worker encodes locally.
4. The worker uploads the finished `-TSD` file back.
5. The controller verifies the output.
6. The controller writes the output beside the original file.
7. Temporary files are cleaned up.

If the controller is offline when the worker finishes, the worker keeps the finished output and waits to upload it later.

## Intel QSV / Quick Sync

The Docker image builds HandBrakeCLI with QSV support and installs Intel media runtime packages where available.

Rebuild after QSV-related Dockerfile changes:

```bash
docker compose build --no-cache hb-web
docker compose up -d hb-web
```

Check QSV inside the container:

```bash
docker exec -it hb-web check-qsv
```

Expected signs of working QSV:

```text
/dev/dri exists
vainfo returns Intel driver details
HandBrake lists qsv_h264, qsv_h265, or qsv_h265_10bit
```

Requirements:

- Intel CPU with enabled iGPU
- Host exposes `/dev/dri/renderD128`
- Compose maps `/dev/dri:/dev/dri`
- Container has access to `video` and `render` groups
- QSV render-device availability is enabled in Settings

Intel `F` and `KF` desktop CPUs usually do not include an iGPU.

## Official Image

Pull:

```bash
docker pull kevina1724/handbrake-tsd-helper:latest
```

Run:

```bash
docker run -d \
  --name handbrake-tsd-helper \
  -p 8081:8080 \
  -v /path/to/media:/media/Media \
  -v /path/to/data:/app/data \
  -v /path/to/presets:/presets \
  --device /dev/dri:/dev/dri \
  kevina1724/handbrake-tsd-helper:latest
```

The `latest` image is published automatically from `main`. Version tags such as
`v1.2.3` also publish `1.2.3` and `1.2` tags.

## Runtime Data

Runtime state is stored in `data/`.

Common files:

```text
data/jobs.json
data/settings.json
data/storage_stats.json
data/events.json
data/beta_library_cache.json
data/beta_scan_index.json
data/beta_tracked_shows.json
data/beta_autoscan_status.json
data/linked_nodes.json
data/mobile_devices.json
data/wizard_presets.json
data/smart_presets.json
data/logs/
```

Do not commit private runtime data, API keys, node secrets, cache files, or logs.

Safe staging example:

```bash
git add README.md Dockerfile docker-compose.yml .gitignore webui worker presets tests
git status --short
```

## Project Layout

```text
handbrake-tsd-helper/
|-- Dockerfile
|-- docker-compose.yml
|-- README.md
|-- presets/
|-- worker/
|-- webui/
|   `-- app/
|       |-- jobs.py
|       |-- node_linking.py
|       |-- routes.py
|       |-- settings.py
|       |-- smart_presets.py
|       |-- storage_stats.py
|       |-- wizard_llm.py
|       |-- static/
|       `-- templates/
|-- tests/
`-- data/
```

## Troubleshooting

### No files appear in Jobs

Check your Docker volume mounts. Media should be mounted under a path the app can browse, commonly `/media/...`.

### Library scan is empty

Open Settings and map at least one movie folder or show folder.

### Posters do not show

Add TMDb credentials in Settings, save, then refresh the Library scan.

### QSV does not show up

Run:

```bash
docker exec -it hb-web check-qsv
```

Confirm `/dev/dri` exists in the container and that the host iGPU is enabled.

### Worker pairing fails

Check that the worker URL is reachable from the controller, generate a fresh pairing code, and confirm both nodes show the expected role in Settings.

### Worker cannot access a media path

Use Auto local then remote or Remote transfer mode. Set a worker temp folder if the default data folder is too small.

### Job looks stuck

Check the job progress, ETA, linked node status, and job log. If needed, cancel the job from the Jobs page.

Restart only when the process is truly stuck:

```bash
docker restart hb-web
```

## Updating

```bash
git pull
docker compose up -d --build
```

After larger UI updates, hard-refresh the browser.

## Roadmap

Current focus:

- Improve Size Wizard recommendations
- Polish Library workflows for shows, seasons, and episodes
- Expand hardware encoder support
- Build the Android companion client on top of the mobile API v1 contract
- Add web user authentication and per-user permissions
- Add notification hooks

## Contributing

Issues, feature ideas, test results, and pull requests are welcome.

Helpful reports include the source filename, codec, resolution, preset or wizard settings, whether the job was local or remote, and the relevant log lines.

## License

MIT. Free for personal, commercial, and homelab use.
