"""
Global configuration for HandBrake TSD Helper.

This file centralizes:
- environment variables
- directory paths
- allowed media roots
- supported video extensions
"""

import os

# -----------------------------
# Video formats we allow browsing/encoding
# -----------------------------
VIDEO_EXTS = (".mkv", ".mp4", ".avi", ".mov", ".m4v")

# -----------------------------
# Allowed browseable storage roots (directory selector UI)
# Format: (path, label)
# -----------------------------
ROOTS = [
    ("/mnt/nas/PLEX_MEDIA", "NAS Plex (/mnt/nas/PLEX_MEDIA)"),
    ("/mnt/media", "Media Disk 1 (/mnt/media)"),
    ("/mnt/media1", "Media Disk 2 (/mnt/media1)"),
]

# Used for validating user-submitted file paths
ALLOWED_PREFIXES = [r[0] for r in ROOTS]


# -----------------------------
# Persistent storage directories
# -----------------------------
DATA_DIR = os.environ.get("HB_DATA_DIR", "/app/data")
LOG_DIR = os.path.join(DATA_DIR, "logs")
JOBS_FILE = os.path.join(DATA_DIR, "jobs.json")
PRESET_CONFIG_FILE = os.path.join(DATA_DIR, "preset_config.json")

# Ensure directories exist when imported
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)


# -----------------------------
# HandBrake preset directory
# -----------------------------
PRESET_DIR = os.environ.get("HB_PRESET_DIR", "/presets")


# -----------------------------
# Default fallback preset config
# Name fields are just human-readable labels
# -----------------------------
DEFAULT_PRESET_CONFIG = {
    "1080": {
        "file": "/presets/full1080.json",
        "name": "Plex-1080p-fullsize",
    },
    "4k": {
        "file": "/presets/4k.json",
        "name": "4kPlex",
    },
}
