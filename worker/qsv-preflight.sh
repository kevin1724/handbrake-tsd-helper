#!/bin/sh
set -u

MODE="${1:-encode}"
RENDER_DEVICE="${TSD_QSV_RENDER_DEVICE:-/dev/dri/renderD128}"
QSV_ADAPTER="${TSD_QSV_ADAPTER:-0}"
VA_DRIVER="${LIBVA_DRIVER_NAME:-iHD}"
PREFIX="[ByteSqueeze]"

case "$QSV_ADAPTER" in
  ''|*[!0-9]*)
    echo "$PREFIX QSV preflight: invalid adapter index '$QSV_ADAPTER'"
    exit 1
    ;;
esac

echo "$PREFIX QSV ${MODE} diagnostics"
echo "$PREFIX /dev/dri:"
ls -l /dev/dri 2>&1 || true
echo "$PREFIX Selected render device: $RENDER_DEVICE"
echo "$PREFIX Intel VA driver: $VA_DRIVER"
echo "$PREFIX Selected QSV adapter: $QSV_ADAPTER"

if [ ! -c "$RENDER_DEVICE" ]; then
  echo "$PREFIX QSV preflight: render device is missing or is not a character device: $RENDER_DEVICE"
  exit 1
fi
if [ ! -r "$RENDER_DEVICE" ] || [ ! -w "$RENDER_DEVICE" ]; then
  echo "$PREFIX QSV preflight: render device is not readable and writable: $RENDER_DEVICE"
  exit 1
fi

if ! command -v vainfo >/dev/null 2>&1; then
  echo "$PREFIX QSV preflight: vainfo is not installed"
  exit 1
fi
VA_OUTPUT=$(vainfo --display drm --device "$RENDER_DEVICE" 2>&1)
VA_STATUS=$?
printf '%s\n' "$VA_OUTPUT"
if [ "$VA_STATUS" -ne 0 ]; then
  echo "$PREFIX QSV preflight: VAAPI initialization failed for $RENDER_DEVICE using $VA_DRIVER"
  exit 1
fi
ACTIVE_VA_DRIVER=$(printf '%s\n' "$VA_OUTPUT" | sed -n 's/^[[:space:]]*vainfo: Driver version:[[:space:]]*/Driver version: /p' | sed -n '1p')
if [ -n "$ACTIVE_VA_DRIVER" ]; then
  echo "$PREFIX Active Intel VA driver: $ACTIVE_VA_DRIVER"
else
  echo "$PREFIX Active Intel VA driver: $VA_DRIVER (selected by LIBVA_DRIVER_NAME)"
fi
echo "$PREFIX VAAPI preflight: passed"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "$PREFIX QSV preflight: ffmpeg is not installed"
  exit 1
fi
QSV_OUTPUT=$(ffmpeg -hide_banner -loglevel error \
  -init_hw_device "qsv:hw,child_device=$RENDER_DEVICE,child_device_type=vaapi" \
  -f lavfi -i "color=size=64x64:duration=0.04" \
  -frames:v 1 -f null - 2>&1)
QSV_STATUS=$?
if [ -n "$QSV_OUTPUT" ]; then
  printf '%s\n' "$QSV_OUTPUT"
fi
if [ "$QSV_STATUS" -ne 0 ]; then
  echo "$PREFIX QSV preflight: QSV device initialization failed for $RENDER_DEVICE"
  exit 1
fi
echo "$PREFIX QSV device preflight: passed"
exit 0
