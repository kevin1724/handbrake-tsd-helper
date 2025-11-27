# ===============================
# HandBrake TSD Helper - WebUI + Worker
# ===============================

# Base image: Python + Debian (for apt / HandBrakeCLI)
FROM python:3.11-slim

# -------------------------------
# System deps + HandBrakeCLI
# -------------------------------
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        handbrake-cli \
        bash \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# -------------------------------
# App directories
# -------------------------------
WORKDIR /app

# Create data dir (job history, logs) and presets dir
RUN mkdir -p /app/data \
    && mkdir -p /presets \
    && mkdir -p /worker

# -------------------------------
# Copy application code
# -------------------------------
# Copy the web UI package (Python package "webui")
# This folder contains: app/__init__.py, app/__main__.py, routes.py, jobs.py, etc.
COPY webui /app/webui

# Copy worker script (encode-one.sh) to /worker
COPY worker/encode-one.sh /worker/encode-one.sh

# Copy default presets into image (can be overridden by volume)
COPY presets /presets

# Make worker script executable
RUN chmod +x /worker/encode-one.sh

# -------------------------------
# Python dependencies
# -------------------------------
RUN pip install --no-cache-dir flask

# -------------------------------
# Environment variables
# -------------------------------
# Where the app stores jobs.json + logs
ENV HB_DATA_DIR=/app/data

# Where preset JSON files are located (user can override via docker-compose)
ENV HB_PRESET_DIR=/presets

# Make Python see /app as the root for imports (so "webui" package works)
ENV PYTHONPATH=/app

# Enable Flask debug / auto-reload behavior
ENV FLASK_ENV=development
ENV FLASK_DEBUG=1

# Optional: unbuffered logs so you see output immediately
ENV PYTHONUNBUFFERED=1

# -------------------------------
# Expose port & default command
# -------------------------------
EXPOSE 8080

# Run the Flask app via the package entrypoint:
#   python -m webui.app
CMD ["python", "-m", "webui.app"]
