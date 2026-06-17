# 🎬 HandBrake TSD Helper - Web UI + Media Encoding Dashboard

HandBrake TSD Helper is a lightweight, self-hosted web dashboard for **HandBrakeCLI**. It is built for NAS boxes, home servers, Plex/Jellyfin/Emby libraries, and anyone who wants safer automated transcoding without living in the HandBrake desktop app.

✅ **TSD stands for "Transcoded"**. Completed output files are tagged with `-TSD`, so the app can skip already-encoded media and avoid duplicate work.

The app has grown into a full media encoding dashboard: browse files, queue jobs, use a size wizard, scan movies and shows, track storage savings, predict final file sizes, pair worker nodes, and optionally remote-transfer jobs to machines that do not have the media drives mounted.

[![Docker Pulls](https://img.shields.io/docker/pulls/kevina1724/handbrake-tsd-helper?style=for-the-badge&logo=docker)](https://hub.docker.com/r/kevina1724/handbrake-tsd-helper)

---

## ✅ Current Progress

The last few update rounds added a lot of major pieces:

- ✅ Modern dark dashboard UI with Jobs, Size Wizard, Library, and Settings pages
- ✅ One-shot encoder with a cleaner file browser, selected-file card, batch tools, and live progress
- ✅ Queue dashboard with queued/running/completed/error metrics, saved storage, runtime, ETA, and clear error status
- ✅ Scrollable job history and scrollable Settings event/storage tables with selectable row counts
- ✅ Safer failed-job cleanup: failed encodes remove the incomplete `-TSD` output and keep the original source
- ✅ Running-job cancel buttons from the one-shot encoder and queue history
- ✅ Estimated final output size while a job is running, checked at light intervals
- ✅ Size Wizard overhaul with AI mode, CPU profile awareness, QSV/codec options, audio/subtitle language controls, previews, and saved wizard presets
- ✅ Movie/show detection in the Size Wizard: movies default to 5 GB, shows default to 800 MB
- ✅ Default copy behavior for English and Spanish audio/subtitle selections
- ✅ Library page for mapped movie/show folders, poster cards, recommendations, sorting, filtering, and queueing
- ✅ Cached library scans so the Library page does not rescan every load
- ✅ Optional poster metadata through TMDb API credentials
- ✅ Show tracking with expandable shows, seasons, and episodes
- ✅ Beta auto-scan every configurable interval using cheap path/size/modified-time checks
- ✅ Auto-queue for tracked shows after file stability checks
- ✅ Multi-node linking with controller/worker roles, secure one-time pairing codes, heartbeat/status, token signing, rotate secret, and unlink
- ✅ Local mounted media mode, auto local-then-remote mode, and remote-transfer mode
- ✅ Remote transfer progress for source download, worker encoding, and finished-file upload back to the controller
- ✅ Worker-specific prediction history so ETA and savings estimates improve per node
- ✅ Settings split into Main, Beta, and Linked Nodes subpages

---

## 🌟 Key Features

- 🌐 **Web UI** - phone, tablet, and desktop friendly
- 🧭 **Modern navigation** - Jobs, Size Wizard, Library, Settings
- 🎛️ **Preset support** - auto 1080p/4K preset detection plus custom HandBrake preset files
- 📥 **Job queue** - safe one-at-a-time local queue with pause, reorder, remove, and cancel
- 📊 **Queue dashboard** - queued/running/completed/errors, saved storage, runtime, progress, ETA
- ⏳ **Live progress** - encode progress, transfer progress, ETA, and estimated final file size
- 📜 **Logs and history** - persisted job history and downloadable logs
- 🧾 **Storage savings** - records before/after file sizes and total saved storage
- 🧠 **Prediction engine** - uses past encode history, preset, HDR/SDR hints, and node history
- 🧙 **Size Wizard** - target-size planning, previews, AI mode, QSV/codec options, and saved wizard presets
- 🎞️ **Library scanner** - maps movie/show folders, caches scans, sorts recommendations, and queues from poster cards
- 📺 **Show tracking** - expands shows into seasons/episodes and can auto-queue new stable episodes
- 🖼️ **Poster metadata** - optional TMDb credentials for movie/show/season artwork
- 🔁 **Auto scan** - configurable background scan with skip-while-encoding and file stability checks
- 🖥️ **Multi-node workers** - pair worker nodes, dispatch jobs, map paths, and monitor remote jobs
- 📡 **Remote-transfer workers** - download source to worker temp storage, encode locally, upload finished output back
- 🛡️ **Safer file handling** - original files are preserved unless output is verified and completed successfully
- 🐳 **Dockerized** - runs as a container with persistent `/app/data`

---

## 📌 Why `-TSD`?

When managing a big media library, you need a clear way to know what has already been processed.

HandBrake TSD Helper:

- ✅ Outputs completed files with `-TSD` in the filename
- ✅ Skips already-transcoded `-TSD` files during browsing and scans
- ✅ Deletes incomplete `-TSD` output if an encode fails
- ✅ Keeps the original source available when a job errors or is canceled
- ✅ Prevents wasted CPU and duplicate encodes

Example:

```text
The.Matrix.2160p.mkv -> The.Matrix.2160p-TSD.mkv
```

---

## 🧭 Pages

### 📥 Jobs

The Jobs page is the main encoder dashboard.

- One-shot file picker with folder and file browsing
- Search, root selector, breadcrumbs, selected-file card
- Auto preset or manual 1080p/4K preset selection
- Open selected file directly in the Size Wizard
- Batch rename and batch encode tools
- Queue metrics, progress bars, ETA, estimated final file size, and saved size
- Job history with adjustable scroll size: 10, 25, 50, or 100 rows
- Cancel running jobs and clear top-level error status
- Linked node panel showing worker health, worker jobs, encoding progress, and transfer progress

### 🧙 Size Wizard

The Size Wizard helps build HandBrake arguments from a target size and quality goal.

- Movie/show auto detection
- Movie default target: 5 GB
- Show default target: 800 MB
- Shows original file size before planning
- AI mode that uses selected CPU profile and user conditions
- QSV, codec, preset, resolution, audio, and subtitle controls
- Default English and Spanish audio/subtitle copy behavior
- Fast preview images and accurate preview clips
- History-based predicted output size and savings
- Save and reuse wizard-created presets

### 🎞️ Library

The Library page is the newer media-management view.

- Scans mapped movie and show folders only
- Loads saved cache first so it does not rescan every page load
- Optional recursive scanning
- Movie poster grid with title, year, quality, HDR/SDR, source size, predicted size, savings, and target codec
- Show cards with episode count, season count, predicted savings, progress bar, tracking, and queue actions
- Expand shows into seasons, then episodes
- Queue single items, seasons, full shows, or selected batches
- Send selected jobs to local queue, best available worker, or a selected worker node
- Recommendations sort to show the biggest likely storage wins first
- HDR/SDR detection uses metadata and filename hints like `HDR`, `DV`, `DoVi`, `REMUX`, `10bit`, `HEVC`, and similar release tags

### ⚙️ Settings

Settings are split into subpages to keep the UI manageable.

- **Main Settings**: encoding defaults, CPU profile, queue UI mode, preset upload/download/delete, events, storage savings
- **Beta Settings**: movie/show folder mapping, posters/TMDb credentials, auto-scan settings
- **Linked Nodes**: local node identity, pairing codes, worker pairing, path mapping, transfer mode, temp folders, rotate secret, unlink

Events and Storage Savings are scrollable blocks so the Settings page does not become a mile long.

---

## 🔁 Beta Auto Scan

Auto scan is designed to stay light on resources.

Every interval, default 30 minutes:

1. Checks if auto scan is enabled
2. Skips if encoding is running and skip-while-encoding is enabled
3. Loads the previous scan index
4. Walks mapped folders only
5. Uses cheap stat checks: path, size, and modified time
6. Fully parses only new or changed video files
7. Ignores already encoded `-TSD` files
8. Marks missing files as removed
9. Saves the scan index and Library cache
10. Auto-queues tracked show episodes only after file stability checks pass

This means normal scans do not need to ffprobe every file every time.

---

## 🖥️ Multi-Node Linking

HandBrake TSD Helper can link multiple app containers/nodes together.

- One node acts as the **controller/master**
- Other nodes act as **workers**
- Workers generate secure one-time pairing codes
- Pairing codes expire quickly and can only be used once
- Nodes use trusted tokens/HMAC-style signed requests
- Workers report heartbeat, queue counts, running jobs, completed jobs, errors, and prediction data
- Controller can send jobs locally, to the best available worker, or to a selected worker
- Worker-specific encode history is kept separate for better ETA predictions

### 🔐 Security Controls

- No unauthenticated node commands
- Pairing codes and secrets are not intended to be logged
- Rotate secret invalidates the old trusted token and replaces it with a new one
- Unlink/revoke removes a worker relationship
- Path mappings are required for local-mounted worker mode

---

## 📡 Worker Transfer Modes

### Local Mounted Media Mode

Use this when the worker can access the same media files through mounted paths.

Example:

```text
Controller path: /media/Movies
Worker path:     /mnt/media/Movies
```

The controller translates the path and sends the job to the worker.

### Auto Local Then Remote

Use this when some worker paths are mounted and others are not.

The controller tries path mapping first. If no mapping matches, it falls back to remote transfer.

### Remote Transfer Mode

Use this when the worker does not have the media drives mounted.

Flow:

1. Controller creates authenticated temporary transfer links
2. Worker downloads the source file to its temp folder
3. Worker encodes the temp file locally
4. Worker uploads the finished `-TSD` output back to the controller/storage node
5. Controller verifies the uploaded output
6. Controller writes the completed output next to the original
7. Original source is deleted only after successful verification
8. Temp files are cleaned up

The Jobs page shows source download progress, encoding progress, and finished-file upload progress for linked worker jobs.

---

## 🏗️ Folder Structure

```text
handbrake-tsd-helper/
│
├── docker-compose.yml
├── Dockerfile
├── README.md
├── .gitignore
│
├── webui/
│   └── app/
│       ├── __init__.py              # Flask app factory
│       ├── __main__.py              # python -m webui.app entry point
│       ├── config.py                # media roots, data paths, preset paths
│       ├── cpu_profiles.py          # CPU profile list for ETA/wizard planning
│       ├── events.py                # event feed persistence
│       ├── jobs.py                  # queue, dispatcher, progress, remote-transfer worker jobs
│       ├── node_linking.py          # pairing, tokens, HMAC signing, transfer grants
│       ├── presets.py               # HandBrake preset config
│       ├── routes.py                # UI/API routes, Library scanner, Size Wizard
│       ├── settings.py              # app settings and defaults
│       ├── storage_stats.py         # encode history and savings tracking
│       ├── static/
│       │   ├── app.js
│       │   └── styleui.css
│       └── templates/
│           ├── index.html           # Jobs dashboard
│           ├── size_wizard.html     # Size Wizard
│           ├── beta.html            # Library page
│           └── settings.html        # Settings subpages
│
├── worker/
│   └── encode-one.sh                # HandBrakeCLI execution script
│
├── presets/
│   ├── full1080.json
│   └── 4k.json
│
└── data/                            # runtime state, not for git
    ├── jobs.json
    ├── settings.json
    ├── storage_stats.json
    ├── events.json
    ├── beta_library_cache.json
    ├── beta_scan_index.json
    ├── beta_tracked_shows.json
    ├── beta_autoscan_status.json
    ├── node_linking.json
    ├── wizard_presets.json
    └── logs/
```

---

## 🐳 Quick Start - Docker Compose

1. Clone the repo:

```bash
git clone https://github.com/kevin1724/handbrake-tsd-helper.git
cd handbrake-tsd-helper
```

2. Edit `docker-compose.yml` and mount your media folders under `/media/...`.

Example:

```yaml
volumes:
  - /path/to/movies:/media/Movies
  - /path/to/shows:/media/Shows
  - ./data:/app/data
  - ./presets:/presets
```

3. Start the stack:

```bash
docker compose up -d --build
```

4. Open the UI:

```text
http://SERVER-IP:8081
```

🎉 Done. Start by opening Settings, mapping your movie/show folders, then scanning the Library.

---

## 🐳 Official Image

Pull the latest image:

```bash
docker pull ghcr.io/kevin1724/handbrake-tsd-helper:latest
```

Run manually:

```bash
docker run -d \
  --name handbrake-tsd-helper \
  -p 8081:8080 \
  -v /path/to/media:/media/Media \
  -v /path/to/data:/app/data \
  -v /path/to/presets:/presets \
  ghcr.io/kevin1724/handbrake-tsd-helper:latest
```

---

## ⚙️ Recommended First Setup

1. Open **Settings -> Main**
2. Pick your CPU profile for better ETA and Size Wizard planning
3. Upload or verify your 1080p and 4K presets
4. Open **Settings -> Beta**
5. Map your movie folders and show folders
6. Add TMDb credentials if you want posters
7. Enable auto scan if desired
8. Open **Library**
9. Run a scan and sort by **Recommendations**
10. Queue a few files and let the app build prediction history

For workers:

1. On the worker node, open **Settings -> Linked Nodes**
2. Generate a pairing code
3. On the controller node, enter the worker URL/IP and pairing code
4. Choose Local, Auto, or Remote transfer mode
5. Add path mappings or remote temp folder as needed
6. Refresh nodes and confirm controller/worker status

---

## 🧠 Prediction History

The app learns from completed jobs.

It records:

- Source size
- Output size
- Saved bytes
- Runtime
- Preset used
- HDR/SDR hint
- Node that ran the job

The Library and Size Wizard use this history to estimate:

- Final output size
- Storage savings
- Runtime/ETA
- Worker-specific timing when dispatching to linked nodes

The more jobs each node completes, the better that node's estimate gets.

---

## 🛡️ Safety Notes

- ✅ Failed jobs delete the incomplete `-TSD` output, not the original source
- ✅ Canceled jobs preserve the original source
- ✅ Remote-transfer output is verified before it is written beside the original
- ✅ Original source deletion only happens after successful encode/verification
- ✅ Already encoded `-TSD` files are ignored by scans and queues
- ✅ Clear buttons ask for confirmation before deleting event/storage history
- ⚠️ Always keep backups of important media before enabling aggressive cleanup behavior

---

## 🔐 API Keys And Cache Files

Do not commit private runtime data.

Keep these out of git:

- `data/settings.json` if it contains TMDb credentials
- `data/beta_library_cache.json`
- `data/beta_scan_index.json`
- `data/beta_tracked_shows.json`
- `data/node_linking.json`
- `data/jobs.json`
- `data/storage_stats.json`
- `data/logs/`

Useful git command:

```bash
git add README.md webui worker presets Dockerfile docker-compose.yml .gitignore
```

Then check what is staged:

```bash
git status --short
```

---

## 🔥 Performance Notes

- Auto scan uses cheap file stat checks before deeper parsing
- Scan cache prevents rescanning the full Library every page load
- File stability checks avoid queueing half-copied episodes
- Running output-size estimates are checked at lightweight progress intervals
- HandBrake thread count can be tuned in Settings
- QSV options are available in the Size Wizard when your hardware/container setup supports it
- Multi-node mode can spread work across multiple machines

---

## ❓ Troubleshooting

### No files appear in Jobs?

Check your Docker volume mounts and make sure media is under `/media/...` or configured roots.

```yaml
volumes:
  - /your/media:/media/Media
```

### Library scan is empty?

Open **Settings -> Beta** and map at least one movie folder or show folder. The Library page scans mapped folders, not the whole drive.

### Posters do not show?

Add TMDb API credentials in **Settings -> Beta**, save, then refresh the Library scan.

### Worker pairing fails?

- Confirm the worker URL is reachable from the controller
- Generate a fresh pairing code on the worker
- Pair before the code expires
- Check **Settings -> Linked Nodes** on both sides for controller/worker status

### Worker cannot access the media path?

Use **Auto local then remote** or **Remote transfer mode**, and set a worker temp folder if the default data folder is too small.

### Job looks stuck?

- Check the job row progress and ETA
- Download the job log
- Check linked node status if it is a worker job
- Cancel the job if needed
- Restart the container only if the process is truly stuck

```bash
docker restart hb-web
```

---

## 🛠️ Updating

```bash
git pull
docker compose up -d --build
```

If the UI changed a lot, hard-refresh your browser after rebuilding.

---

## 🗺️ Roadmap

Already completed:

- ✅ Modern dark UI
- ✅ Size Wizard overhaul
- ✅ Saved wizard presets
- ✅ Library scanner with posters and recommendations
- ✅ Cached scans and mapped movie/show folders
- ✅ Auto scan and tracked show auto-queue
- ✅ Storage savings history and prediction engine
- ✅ Multi-node linking
- ✅ Remote-transfer worker mode
- ✅ Node-specific prediction history
- ✅ Safer failed-job cleanup

Possible next steps:

- 🔜 Authentication and multi-user permissions
- 🔜 Webhook/email notifications
- 🔜 More hardware encoder presets
- 🔜 Better per-title quality recommendations
- 🔜 Full Library rename from Beta once it feels finished

---

## 🤝 Contributing

Issues, feature ideas, testing notes, and PRs are welcome.

This project is especially useful when real media-library edge cases show up, so bug reports with filenames, codec details, and workflow notes help a lot.

---

## 📄 License

MIT - free for personal, commercial, and homelab use.

---

## 💙 Built For Media Nerds

If you:

- ✅ hoard TBs of movies and shows
- ✅ run Plex, Jellyfin, or Emby
- ✅ care about saving storage
- ✅ want automation without losing control
- ✅ like seeing exactly what your encodes are doing

...this tool was made for you 😎

Enjoy, and happy transcoding!
