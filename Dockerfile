# ===============================
# HandBrake TSD Helper - WebUI + Worker
# ===============================
#
# QSV note:
# The distro handbrake-cli package can install cleanly while still lacking
# usable Intel QSV encoders. Build HandBrakeCLI from source with --enable-qsv
# so the container exposes qsv_h264/qsv_h265/qsv_h265_10bit when /dev/dri and
# the Intel media runtime are available.

# Pin Bookworm so older Intel Media SDK/libmfx packages remain available for
# legacy QSV nodes such as UHD 630. The floating python:3.11-slim tag can move
# to newer Debian releases where those packages are removed.
ARG PYTHON_IMAGE=python:3.11-slim-bookworm
ARG HANDBRAKE_VERSION=1.9.2

FROM ${PYTHON_IMAGE} AS handbrake-builder

ARG HANDBRAKE_VERSION

RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's/^Components: .*/Components: main contrib non-free non-free-firmware/' /etc/apt/sources.list.d/debian.sources; \
    elif [ -f /etc/apt/sources.list ]; then \
      sed -i 's/ main/ main contrib non-free non-free-firmware/g' /etc/apt/sources.list; \
    fi; \
    apt-get update; \
    qsv_build_deps=""; \
    for pkg in libvpl-dev libmfx-gen-dev libmfx-dev intel-mediasdk; do \
      if apt-cache show "$pkg" >/dev/null 2>&1; then qsv_build_deps="$qsv_build_deps $pkg"; fi; \
    done; \
    if [ -z "$qsv_build_deps" ]; then \
      echo "ERROR: No Intel QSV development package found (expected libvpl-dev, libmfx-gen-dev, libmfx-dev, or intel-mediasdk)."; \
      exit 1; \
    fi; \
    apt-get install -y --no-install-recommends \
      autoconf \
      automake \
      autopoint \
      bash \
      bison \
      build-essential \
      ca-certificates \
      cmake \
      cargo \
      curl \
      git \
      libass-dev \
      libbz2-dev \
      libdrm-dev \
      libfontconfig1-dev \
      libfreetype6-dev \
      libfribidi-dev \
      libharfbuzz-dev \
      libjansson-dev \
      liblzma-dev \
      libmp3lame-dev \
      libnuma-dev \
      libogg-dev \
      libopus-dev \
      libsamplerate0-dev \
      libspeex-dev \
      libtheora-dev \
      libtool \
      libtool-bin \
      libturbojpeg0-dev \
      libva-dev \
      libvorbis-dev \
      libvpx-dev \
      libx264-dev \
      libx265-dev \
      m4 \
      make \
      meson \
      nasm \
      ninja-build \
      patch \
      pkg-config \
      python3 \
      python3-setuptools \
      rustc \
      tar \
      yasm \
      zlib1g-dev \
      $qsv_build_deps; \
    git clone --depth 1 --branch "${HANDBRAKE_VERSION}" https://github.com/HandBrake/HandBrake.git /tmp/HandBrake; \
    cd /tmp/HandBrake; \
    ./configure --disable-gtk --enable-qsv --launch-jobs="$(nproc)" --launch; \
    install -m 0755 build/HandBrakeCLI /usr/local/bin/HandBrakeCLI; \
    /usr/local/bin/HandBrakeCLI --version

FROM ${PYTHON_IMAGE}

# ------------------------------------------------
# Enable contrib + non-free + non-free-firmware.
# Intel's iHD media driver is in non-free on Debian-based images.
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
    apt-get update; \
    qsv_runtime_deps=""; \
    if apt-cache show intel-media-va-driver-non-free >/dev/null 2>&1; then \
      qsv_runtime_deps="$qsv_runtime_deps intel-media-va-driver-non-free"; \
    elif apt-cache show intel-media-va-driver >/dev/null 2>&1; then \
      qsv_runtime_deps="$qsv_runtime_deps intel-media-va-driver"; \
    fi; \
    if apt-cache show i965-va-driver-shaders >/dev/null 2>&1; then \
      qsv_runtime_deps="$qsv_runtime_deps i965-va-driver-shaders"; \
    elif apt-cache show i965-va-driver >/dev/null 2>&1; then \
      qsv_runtime_deps="$qsv_runtime_deps i965-va-driver"; \
    fi; \
    for pkg in \
      libmfx1 \
      intel-mediasdk \
      libmfx-gen1.2 \
      libvpl2 \
      libvpl-tools \
      libigfxcmrt7; do \
      if apt-cache show "$pkg" >/dev/null 2>&1; then qsv_runtime_deps="$qsv_runtime_deps $pkg"; fi; \
    done; \
    if apt-cache show libvpx9 >/dev/null 2>&1; then \
      qsv_runtime_deps="$qsv_runtime_deps libvpx9"; \
    elif apt-cache show libvpx8 >/dev/null 2>&1; then \
      qsv_runtime_deps="$qsv_runtime_deps libvpx8"; \
    elif apt-cache show libvpx7 >/dev/null 2>&1; then \
      qsv_runtime_deps="$qsv_runtime_deps libvpx7"; \
    fi; \
    for pkg in libx264-164 libx264-163 libx264-160 libx265-215 libx265-209 libx265-199; do \
      if apt-cache show "$pkg" >/dev/null 2>&1; then qsv_runtime_deps="$qsv_runtime_deps $pkg"; fi; \
    done; \
    apt-get install -y --no-install-recommends \
      bash \
      ca-certificates \
      ffmpeg \
      intel-gpu-tools \
      libass9 \
      libbz2-1.0 \
      libdrm2 \
      libfontconfig1 \
      libfreetype6 \
      libfribidi0 \
      libgomp1 \
      libharfbuzz0b \
      libjansson4 \
      liblzma5 \
      libnuma1 \
      libogg0 \
      libopus0 \
      libsamplerate0 \
      libspeex1 \
      libstdc++6 \
      libtheora0 \
      libturbojpeg0 \
      libva-drm2 \
      libva2 \
      libvorbis0a \
      vainfo \
      zlib1g \
      $qsv_runtime_deps; \
    rm -rf /var/lib/apt/lists/*

COPY --from=handbrake-builder /usr/local/bin/HandBrakeCLI /usr/local/bin/HandBrakeCLI

# -------------------------------
# App directories
# -------------------------------
WORKDIR /app

RUN mkdir -p /app/data /presets /worker

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
# QSV diagnostics helper
# -------------------------------
RUN set -eux; \
    printf '%s\n' \
      '#!/bin/sh' \
      'set -eu' \
      'echo "=== HandBrake ==="' \
      'HandBrakeCLI --version || true' \
      'echo' \
      'echo "=== /dev/dri ==="' \
      'ls -l /dev/dri 2>/dev/null || echo "/dev/dri is not mounted into this container"' \
      'echo' \
      'echo "=== Intel media packages ==="' \
      'dpkg -l | grep -Ei "intel-media|intel-mediasdk|libmfx|libvpl|i965|igfx" || true' \
      'echo' \
      'echo "=== VA drivers ==="' \
      'find /usr/lib -path "*/dri/*_drv_video.so" -print 2>/dev/null | sort || true' \
      'echo' \
      'echo "=== VAAPI ==="' \
      'vainfo --display drm --device /dev/dri/renderD128 2>&1 || true' \
      'echo' \
      'echo "=== VAAPI with i965 fallback ==="' \
      'LIBVA_DRIVER_NAME=i965 vainfo --display drm --device /dev/dri/renderD128 2>&1 || true' \
      'echo' \
      'echo "=== HandBrake encoders ==="' \
      'HandBrakeCLI --help 2>&1 | sed -n "/Select video encoder/,/Select audio encoder/p" | grep -i "qsv\\|265\\|264" || true' \
      > /usr/local/bin/check-qsv; \
    chmod +x /usr/local/bin/check-qsv

# -------------------------------
# Environment variables
# -------------------------------
ENV HB_DATA_DIR=/app/data
ENV HB_PRESET_DIR=/presets

# Force Intel iHD driver. This is the normal VAAPI/QSV driver for modern Intel.
ENV LIBVA_DRIVER_NAME=iHD
ENV MFX_IMPL_HARDWARE=1

ENV PYTHONPATH=/app
ENV FLASK_ENV=development
ENV FLASK_DEBUG=1
ENV PYTHONUNBUFFERED=1

# -------------------------------
# Expose port & start app
# -------------------------------
EXPOSE 8080
CMD ["python", "-m", "webui.app"]
