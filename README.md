🎬 HandBrake TSD Helper — Web UI + Automated Transcoding Queue

HandBrake TSD Helper is a lightweight, self-hostable web interface for HandBrakeCLI — built for NAS owners, Plex users, and media hoarders who want simple, safe, automated transcoding without launching a desktop GUI.

Browse media folders, queue encodes, batch-process entire shows, track progress, pause the queue, download logs, rename files, and automatically avoid double-encoding — all from a clean dark-mode web UI.

🔤 What does TSD mean?

TSD = Transcoded

It’s our shorthand tag appended to finished files:

MovieName- TSD.mkv


✅ Indicates the file has already been processed
✅ Prevents accidental re-encoding
✅ Keeps Plex/Sonarr/Radarr libraries tidy
✅ Works perfectly with bulk automation

If a filename already ends in -TSD, the system politely skips it. No wasted CPU, no duplicates — just clean media.

✅ Key Features

🌐 Web UI — accessible from any device

🧭 File browser — visually pick media files

🎚️ Preset selector (1080p / 4K included)

📥 Automatic job queue — one at a time

⏳ Live progress + streaming logs

🛑 Cancel running encodes

✂️ Remove jobs from queue

🔀 Pause/resume queue anytime

📂 Batch encode entire folders

🔁 Recursive scanning for TV seasons

🚫 Auto-skip already transcoded (-TSD)

🏷 Batch rename helper for consistency

📜 Job history survives container restarts

📄 Per-job log downloads

🌙 Modern dark-mode UI

🐳 Fully Dockerized — no HandBrake install required

🎯 Project Goals

✔ Make HandBrakeCLI approachable
✔ Protect media libraries from mistakes
✔ Automate long batch encodes
✔ Run reliably on home servers
✔ Stay clean, fast, and self-hosted

Not trying to be a full media-management system — just the best darn encoding helper.

🏗️ Folder Structure
handbrake-tsd-helper/
│
├── docker-compose.yml
├── Dockerfile
│
├── webui/                  ← Flask web server
│   ├── __init__.py
│   ├── routes.py
│   ├── jobs.py
│   ├── presets.py
│   ├── config.py
│   └── templates/          ← HTML
│
├── worker/
│   └── encode-one.sh       ← Runs HandBrakeCLI encode
│
├── presets/                ← Your HandBrake preset JSONs
│   ├── full1080.json
│   └── 4k.json
│
└── data/                   ← Persistent job state
    └── jobs.json

🐳 Run With Docker Compose

1️⃣ Clone repo:

git clone git@github.com:kevin1724/handbrake-tsd-helper.git
cd handbrake-tsd-helper


2️⃣ Start:

docker compose up -d --build


3️⃣ Open UI:

http://SERVER-IP:8081


✅ Works from desktop, tablet, or phone.

⚙️ Requirements

Docker + Docker Compose

Linux server or NAS

Media mounted into container

CPU encoding (GPU optional soon)

Tested on:

✅ Ubuntu / Debian
✅ Proxmox LXC bind-mounts
✅ TrueNAS SCALE
✅ UnRAID
✅ NFS + SMB shares

🧭 Everyday Usage

Pick a storage root

Browse to a folder

Select a file

Choose preset

Click Start Encode

Chill — logs + progress update live

Batch workflows?

✅ Yes
Recursive TV-season processing?

✅ Yes

📦 Batch Encoding
Encode everything inside one folder:

✅ Great for movie libraries

Recursive mode (includes subfolders):

✅ Perfect for shows:

Shows/
 └── The Office/
     ├── Season 1
     ├── Season 2
     └── Season 3


Each file is automatically queued — safely.

🛡️ Safety Features

✅ Auto-skip already transcoded files (-TSD)
✅ Never escapes allowed media directories
✅ No overwriting originals unless you modify script
✅ Cancel kills current encode safely
✅ Job state auto-recovers after container restart

🧹 Optional — Delete Original After Success

Inside worker/encode-one.sh, uncomment:

rm -f "$SRC"


⚠️ Be 100% sure before enabling.

🔥 Performance Notes

Uses all CPU threads

Includes solid x265 presets

Ideal for home Plex servers

Faster than GUI when batch-encoding

GPU support coming — NVIDIA + QSV planned.

🔁 Updating
git pull
docker compose up -d --build


Done ✅

❓ Common Issues
UI shows empty folders?

Fix your volume mounts:

- /path/to/media:/mnt/media:ro

Permission denied on write?
sudo chown -R 1000:1000 /path/to/media

Queue won’t start?

Check that storage paths exist inside container.

🧭 Roadmap

✅ Remove-from-queue controls
✅ Pause/resume dispatcher
⬜ GPU encode support
⬜ Web authentication
⬜ Drag-and-drop upload
⬜ Notifications (Discord/webhook)
⬜ Multi-output presets
⬜ Auto Plex library refresh

🤝 Contributing

Ideas, bugs, UI tweaks, preset suggestions — all welcome.
Open an issue or PR anytime.

📄 License

MIT — use freely, self-host happily.