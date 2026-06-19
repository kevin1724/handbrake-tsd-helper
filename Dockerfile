# ===============================
# HandBrake TSD Helper - WebUI + Worker
# ===============================


FROM python:3.11-slim-bookworm

# ------------------------------------------------
# Enable contrib + non-free + non-free-firmware
# Needed for Intel iGPU media drivers.
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
# System deps
#
# handbrake-cli is kept for software encodes.
# FFmpeg + VAAPI are used by worker/encode-one.sh for GPU encodes because
# FFmpeg already works with your Intel GPU while Debian trixie HandBrake QSV fails.
# ------------------------------------------------
RUN apt-get install -y --no-install-recommends \
        handbrake-cli \
        ffmpeg \
        bash \
        ca-certificates \
        jq \
        \
        # VAAPI runtime + info tool
        libva2 \
        libva-drm2 \
        libva-x11-2 \
        vainfo \
        \
        # Intel iGPU media drivers
        intel-media-va-driver-non-free \
        i965-va-driver-shaders \
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

# Force Intel iHD driver for newer Intel iGPUs like UHD 630.
ENV LIBVA_DRIVER_NAME=iHD

# Default GPU path used by FFmpeg VAAPI mode.
ENV VAAPI_DEVICE=/dev/dri/renderD128

# auto = use FFmpeg VAAPI when qsv_* encoder is requested, otherwise HandBrake.
# handbrake = always use HandBrakeCLI.
# vaapi = force FFmpeg VAAPI.
ENV TSD_GPU_MODE=auto

ENV PYTHONPATH=/app
ENV FLASK_ENV=development
ENV FLASK_DEBUG=1
ENV PYTHONUNBUFFERED=1

# -------------------------------
# Expose port & start app
# -------------------------------
EXPOSE 8080
CMD ["python", "-m", "webui.app"]
