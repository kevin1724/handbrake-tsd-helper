
# 🎬 HandBrake TSD Helper — Web UI + Automated Transcoding Queue

HandBrake TSD Helper is a lightweight, self-hostable web interface for **HandBrakeCLI** — built for NAS, media servers, and Plex users who want simple, safe, automated transcoding without opening a desktop GUI.

Browse media folders, queue encodes, batch-process entire shows, track live progress, download logs, rename files, skip already-transcoded content — all from a clean dark-mode web UI.

---

## ✅ Key Features

- 🌐 Web UI — accessible from any device
- 🧭 File browser — pick files visually
- 🎚️ Preset selector (1080p / 4K included)
- 📥 Queue system — jobs run one-by-one
- ⏳ Live progress + real-time logs
- 🛑 Cancel running encodes
- 📂 Batch encode an entire folder
- 🔁 Recursive encode (all subfolders — ideal for TV seasons)
- 🚫 Automatically skips files already ending in `-TSD`
- 🏷️ Batch rename tool to append `-TSD`
- 📜 Job history persists across container restarts
- 🧾 Download logs for each job
- 🌙 Modern dark-mode UI
- 🐳 Fully Dockerized — zero system dependencies required

---

## 📌 Project Goals

✔ Make HandBrakeCLI usable from a phone, tablet, or browser  
✔ Protect media libraries from re-encoding mistakes  
✔ Automate large batch workflows — set and forget  
✔ Stay simple, lightweight, fast, and self-hosted

---

## 🏗️ Folder Structure

```
handbrake-tsd-helper/
│
├── docker-compose.yml
│
├── webui/
│   ├── Dockerfile
│   └── app.py              ← Flask web server
│
├── worker/
│   └── encode-one.sh       ← Runs actual HandBrakeCLI encode
│
├── presets/
│   ├── full1080.json
│   └── 4k.json
│
└── data/
    └── jobs.json           ← Saved job history & queue
```

---

## 🐳 Run With Docker Compose

1. Clone repo:

```bash
git clone git@github.com:kevin1724/handbrake-tsd-helper.git
cd handbrake-tsd-helper
```

2. Start:

```bash
docker compose up -d --build
```

3. Open the UI:

```
http://SERVER-IP:8081
```

---

## ⚙️ Requirements

- Docker + Docker Compose
- Linux host — Ubuntu, Debian, Proxmox, UnRAID, TrueNAS, etc.
- Media directories mounted on host (SMB/NFS ok)
- CPU-based encoding (GPU support coming soon)

Tested on:

- Intel i5, i7 home servers
- NFS-mounted Plex libraries
- Proxmox LXC bind-mounts

---

## 🧭 Usage Workflow

1️⃣ Select a storage root  
2️⃣ Browse into movie/show folder  
3️⃣ Click a file to select it  
4️⃣ Choose preset (1080p or 4K)  
5️⃣ Click **Start Encode**  
6️⃣ Watch progress, logs, and job history update  
7️⃣ Wait for completion ✅

---

## 📦 Batch Encoding

### Encode all videos in folder:

✅ Great for movie collections

### Recursive encode (includes subfolders):

✅ Perfect for TV shows with Season folders:

```
Shows/
 └── Breaking Bad/
     ├── Season 01/
     ├── Season 02/
     └── Season 03/
```

Both queue encodes safely — one at a time.

---

## 🛡️ Safety Features

✅ Automatically skips files already tagged `-TSD`  
✅ Prevents accidental double-encoding  
✅ Will not encode outside configured media directories  
✅ Won’t overwrite existing files unless explicitly defined  
✅ Cancel button terminates running encoder safely

---

## 🧹 Optional — Delete Original After Encoding

Modify `worker/encode-one.sh`:

```bash
rm -f "$SRC"
```

Disabled by default for safety.

---

## 🔥 Performance Notes

- Optimized x265 CPU presets included
- Dual-pass CRF 20 recommended balance
- Uses all available CPU threads
- Ideal for low-power home servers

---

## 🛠 Updating

```bash
git pull
docker compose up -d --build
```

---

## ❓ Troubleshooting

### UI loads but no files?
Check bind mounts in `docker-compose.yml`

### Output cannot be written?
Fix permissions:

```bash
sudo chown -R 1000:1000 /mnt/media
```

### Job stuck or unresponsive?
Restart container:

```bash
docker restart hb-web
```

---

## 📍 Roadmap / Planned Enhancements

- ✅ GPU encoding support (Intel/NVIDIA)
- ✅ Push notifications on completion
- ✅ Upload custom HandBrake presets via UI
- ✅ Move/delete output location selector
- ✅ Web auth & user permissions
- ✅ Plex library auto-refresh
- ✅ Docker Hub prebuilt images

---

## 🤝 Contributing

PRs & feature requests welcome!

---

## 📄 License

MIT — free for personal, commercial & self-hosted use.

---
