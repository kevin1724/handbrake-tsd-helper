# ===============================
# HandBrake TSD Helper - WebUI + Worker
# ===============================

FROM python:3.11-slim-bookworm

# ------------------------------------------------
# Enable contrib + non-free + non-free-firmware
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
# System deps + HandBrakeCLI + FFmpeg + Intel VAAPI/QSV tools
# ------------------------------------------------
RUN apt-get install -y --no-install-recommends \
        handbrake-cli \
        ffmpeg \
        bash \
        ca-certificates \
        jq \
        pciutils \
        procps \
        vainfo \
        libva2 \
        libva-drm2 \
        libva-x11-2 \
        intel-media-va-driver-non-free \
        intel-gpu-tools \
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