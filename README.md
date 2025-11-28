# 🎬 HandBrake TSD Helper — Web UI + Automated Transcoding Queue

HandBrake TSD Helper is a lightweight, self-hostable web interface for **HandBrakeCLI** — built for NAS, home servers, media hoarders, and Plex users who want simple, safe, automated transcoding without ever opening a desktop GUI.

✅ **TSD stands for “Transcoded”** — files that finish encoding are tagged with `-TSD` so the system never touches them again, preventing duplicates, wasted CPU, and library chaos.

Browse media folders, queue encodes, batch‑process entire shows, track real‑time progress, download logs, rename files, skip already‑transcoded content — all from a clean, fast, dark‑mode web UI.

[![Docker Pulls](https://img.shields.io/docker/pulls/kevina1724/handbrake-tsd-helper?style=for-the-badge&logo=docker)](https://hub.docker.com/r/kevina1724/handbrake-tsd-helper)



---

## ✅ Key Features

- 🌐 Web UI — accessible from phone, tablet, or desktop
- 🧭 File browser — visually pick media to encode
- 🎚️ Auto 1080p/4K preset detection
- 📥 Job queue — encodes run one‑at‑a‑time safely
- ⏳ Live progress + streaming logs
- 🛑 Cancel running jobs instantly
- 📂 Batch encode entire folders
- 🔁 Recursive encode — perfect for TV seasons
- 🚫 Skips files already ending in `-TSD`
- 🏷️ Batch rename tool to add `-TSD`
- 🧾 Job history survives container restarts
- 📜 Downloadable log files per job
- 🌙 Modern dark‑mode UI
- 🐳 Fully Dockerized — zero system packages required

---

## 📌 Why “TSD”?

When managing huge libraries, you never want to guess what’s been transcoded already.

So HandBrake TSD Helper:
- Outputs files with `-TSD` in the filename  
- Detects & skips them on future scans  
- Prevents accidental re‑encoding  
- Saves time, CPU, electricity & sanity ✅

Example:

```
The.Matrix.2160p.mkv   →   The.Matrix.2160p-TSD.mkv
```

---

## 🏗️ Folder Structure

```
handbrake-tsd-helper/
│
├── docker-compose.yml
├── Dockerfile                 ← Builds hb-web container
├── README.md
├── .gitignore
│
├── webui/                     ← Main Flask application package
│   ├── __init__.py            ← App factory (create_app)
│   ├── __main__.py            ← Allows `python -m webui`
│   ├── config.py              ← Global paths, env vars, ROOTS, defaults
│   ├── presets.py             ← Preset scanning, loading, auto-detect name
│   ├── jobs.py                ← Job queue, dispatcher, persistence
│   ├── routes.py              ← All Flask API/UI endpoints
│   ├── templates/
│   │   └── index.html         ← Main Web UI (HTML + JS)
│   └── static/
│       └── (future CSS/JS/img if added)
│
├── worker/                    ← Encoding execution environment
│   └── encode-one.sh          ← Runs HandBrakeCLI using env vars
│
├── presets/                   ← HandBrake preset JSON library
│   ├── full1080.json
│   └── 4k.json
│
└── data/                      ← Persistent runtime storage
    ├── jobs.json              ← Restored queue + history on restart
    └── logs/                  ← Per-job HandBrake output logs
```

---

## 🐳 Quick Start — Run With Docker Compose

1. Clone repo:

```bash
git clone https://github.com/kevin1724/handbrake-tsd-helper.git
cd handbrake-tsd-helper
```

2. Start the stack:

```bash
docker compose up -d --build
```

3. Open the UI:

```
http://SERVER-IP:8081
```

🎉 Done — start transcoding!

---

🐳 Official Docker Image

You can pull the prebuilt container directly:

Pull the latest image
docker pull ghcr.io/kevin1724/handbrake-tsd-helper:latest

Run it manually
docker run -d \
  --name handbrake-tsd-helper \
  -p 8081:8081 \
  -v /path/to/media:/mnt/media \
  -v /path/to/data:/app/data \
  ghcr.io/kevin1724/handbrake-tsd-helper:latest

📄 Example docker-compose.yml

Here is a clean, ready-to-use docker-compose.yml

```
version: "3.9"

services:
  hb-web:
    image: ghcr.io/kevin1724/handbrake-tsd-helper:latest
    container_name: handbrake-tsd-helper
    ports:
      - "8081:8081"
    volumes:
      # Media folders mounted into /mnt
      - /path/to/media1:/mnt/media1
      - /path/to/media2:/mnt/media2

      # Persistent app data (jobs, logs)
      - /path/to/data:/app/data

      # Optional: Custom HandBrake presets
      - ./presets:/app/presets

    restart: unless-stopped
    
```


✔ Works with multiple media disk mounts
✔ Keeps job history
✔ Automatically loads custom preset JSON files
✔ Fully portable and NAS-friendly

---

## ⚙️ Requirements

- Docker + Docker Compose
- Linux server recommended (Ubuntu, Debian, Proxmox, UnRAID, TrueNAS…)
- Media directories mounted into container
- CPU‑based encoding (GPU support planned)

Tested on:

- Intel i5, i7, Xeon home servers
- Proxmox LXCs with bind mounts
- NFS/SMB mounted Plex media shares

---

## 🧭 Typical Workflow

1️⃣ Pick a storage root  
2️⃣ Browse into a movie/show folder  
3️⃣ Select a file  
4️⃣ Choose preset (or auto)  
5️⃣ Click **Start Encode**  
6️⃣ Watch progress + logs update live  
7️⃣ File is output with `-TSD` ✅

---

## 📦 Batch Encoding

### Encode only current folder
✅ Great for movie folders

### Encode recursively (all subfolders)
✅ Ideal for full TV libraries

Example:

```
Shows/
 └── Breaking Bad/
     ├── Season 01/
     ├── Season 02/
     └── Season 03/
```

Every episode gets queued — safely, automatically.

---

## 🛡️ Safety Features

- ✅ Avoids re‑encoding — thanks to `-TSD` detection
- ✅ Never escapes configured media directories
- ✅ Cancel button safely kills active process
- ✅ Won’t overwrite files unless preset script does
- ✅ Persists queue + job history across crashes/restarts

---

## 🧹 Optional — Delete Originals After Encoding

Inside `worker/encode-one.sh`, uncomment:

```bash
rm -f "$SRC"
```

⚠️ Disabled by default — protect your media!

---

## 🔥 Performance Notes

- Includes tuned x265 presets
- Recommended CRF: 20 (quality vs size sweet spot)
- Fully multi‑threaded — uses all CPU cores
- Works great on low‑power servers & NAS boxes

---

## 🛠 Updating

```bash
git pull
docker compose up -d --build
```

---

## ❓ Troubleshooting

### No files appear?
Check directory mounts:

```yaml
volumes:
  - /your/media:/mnt/media
```

### Can't write output?
Fix permissions:

```bash
sudo chown -R 1000:1000 /your/media
```

### Job frozen?
Restart UI container:

```bash
docker restart hb-web
```

---

## 📍 Roadmap

- ✅ Job removal & queue pausing
- ✅ Auto‑detected preset names
- ✅ Persistent logs
- 🔜 GPU support (Intel/NVIDIA)
- 🔜 Upload presets through UI
- 🔜 Optional email/webhook alerts
- 🔜 Auth & multi‑user permissions
- 🔜 Docker Hub image

---

## 🤝 Contributing

Issues, PRs, feature ideas — all welcome!

---

## 📄 License

MIT — free for personal, commercial & homelab use.

---

## 💙 Built For Media Nerds

If you:

✅ hoard TBs of movies  
✅ run Plex, Jellyfin, or Emby  
✅ care about efficiency & organization  
✅ want automation without complexity…

…this tool was made for you 😎

---

Enjoy, and happy transcoding!
