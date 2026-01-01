# ===============================
# HandBrake TSD Helper - WebUI + Worker
# ===============================

FROM python:3.11-slim

# ------------------------------------------------
# Enable contrib + non-free + non-free-firmware (Debian trixie uses deb822)
# ------------------------------------------------
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's/^Components: .*/Components: main contrib non-free non-free-firmware/' /etc/apt/sources.list.d/debian.sources; \
    elif [ -f /etc/apt/sources.list ]; then \
      sed -i 's/ main/ main contrib non-free non-free-firmware/g' /etc/apt/sources.list; \
    else \
      echo "ERROR: No apt sources file found"; \
      exit 1; \
    fi; \
    apt-get update

# ------------------------------------------------
# System deps + HandBrakeCLI + ffmpeg + Intel QSV/VAAPI + tools
# ------------------------------------------------
RUN apt-get install -y --no-install-recommends \
        handbrake-cli \
        ffmpeg \
        bash \
        ca-certificates \
        \
        # VAAPI runtime + info tool
        libva2 \
        libva-drm2 \
        libva-x11-2 \
        vainfo \
        \
        # ✅ Intel iGPU driver (this is the one that actually exists in Debian repos)
        intel-media-va-driver-non-free \
    && rm -rf /var/lib/apt/lists/*

# -------------------------------
# App directories
# -------------------------------
WORKDIR /app

RUN mkdir -p /app/data \
    && mkdir -p /presets \
    && mkdir -p /worker

# -------------------------------
# Copy application code
# -------------------------------
COPY webui /app/webui
COPY worker/encode-one.sh /worker/encode-one.sh
COPY presets /presets

RUN chmod +x /worker/encode-one.sh

# -------------------------------
# Python dependencies
# -------------------------------
RUN pip install --no-cache-dir flask

# -------------------------------
# Environment variables
# -------------------------------
ENV HB_DATA_DIR=/app/data
ENV HB_PRESET_DIR=/presets

# Force Intel iHD driver (same approach as Plex)
ENV LIBVA_DRIVER_NAME=iHD

ENV PYTHONPATH=/app
ENV FLASK_ENV=development
ENV FLASK_DEBUG=1
ENV PYTHONUNBUFFERED=1

# -------------------------------
# Expose port & start app
# -------------------------------
EXPOSE 8080
CMD ["python", "-m", "webui.app"]
