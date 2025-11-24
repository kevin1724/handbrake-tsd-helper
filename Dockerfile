# ===============================
# HandBrake TSD Helper - WebUI + Worker
# Single container with:
#  - Flask web app
#  - HandBrakeCLI
#  - encode-one.sh worker script
#  - default presets under /presets
# ===============================

# Base image: Python + Debian (for apt / handbrake-cli)
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
# Main app dir
WORKDIR /app

# Create data dir (job history, logs) and presets dir
RUN mkdir -p /app/data \
    && mkdir -p /presets \
    && mkdir -p /worker

# -------------------------------
# Copy application code
# -------------------------------
# Copy the web UI package (Python package "webui")
# Make sure this folder contains: __init__.py, __main__.py, routes.py, jobs.py, presets.py, config.py, etc.
COPY webui /app/webui

# Copy worker script (encode-one.sh) to /worker
COPY worker/encode-one.sh /worker/encode-one.sh

# Copy default presets into image (user can override via volume)
COPY presets /presets

# Make worker script executable
RUN chmod +x /worker/encode-one.sh

# -------------------------------
# Python dependencies
# -------------------------------
# We only need Flask right now. If you add more deps later,
# it's better to add a requirements.txt and install from that.
RUN pip install --no-cache-dir flask

# -------------------------------
# Environment variables
# -------------------------------
# Where the app stores jobs.json + logs
ENV HB_DATA_DIR=/app/data

# Where preset JSON files are located (user can override via docker-compose)
ENV HB_PRESET_DIR=/presets

# Python path to find the "webui" package
ENV PYTHONPATH=/app

# -------------------------------
# Expose port & default command
# -------------------------------
EXPOSE 8080

# Run the Flask app via the package entrypoint:
#   python -m webui.app
CMD ["python", "-m", "webui.app"]
