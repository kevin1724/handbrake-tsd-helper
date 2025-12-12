#!/bin/sh
set -e

# SRC should be a FULL path as seen on the host,
# e.g. /mnt/media/media/Movies/MovieFolder/MyMovie.mkv
SRC="$SRC"

if [ -z "$SRC" ]; then
  echo "ERROR: You must pass the source file via -e SRC=/path/to/file.mkv"
  exit 1
fi

if [ ! -f "$SRC" ]; then
  echo "ERROR: File not found inside container: $SRC"
  echo "Make sure the path starts with /mnt/nas/PLEX_MEDIA, /mnt/media, or /mnt/media1"
  exit 1
fi

# Default suffix for transcoded files
SUFFIX="${SUFFIX:-TSD}"

DIR=$(dirname "$SRC")
BASE=$(basename "$SRC")
EXT="${BASE##*.}"
NAME="${BASE%.*}"

# 🔒 Skip if this file already looks TSD-tagged
LOWER_NAME=$(printf '%s\n' "$NAME" | tr 'A-Z' 'a-z')
if echo "$LOWER_NAME" | grep -q -- '-tsd$'; then
  echo "INFO: Source already has -TSD tag, skipping encode: $SRC"
  exit 0
fi

OUT="${DIR}/${NAME}-${SUFFIX}.${EXT}"

# Preset info comes from env (set by jobs.py based on preset key)
PRESET_FILE="${HB_PRESET_FILE:-/presets/my-presets.json}"
PRESET_NAME="${HB_PRESET_NAME:-MyPresetName}"

echo "=== HandBrake one-shot encode ==="
echo "Source : $SRC"
echo "Target : $OUT"
echo "Suffix : -$SUFFIX"
echo "Preset file : $PRESET_FILE"
echo "Preset name : $PRESET_NAME"
echo "=================================="

# Safety: don't overwrite an existing output file
if [ -f "$OUT" ]; then
  echo "ERROR: Output already exists: $OUT"
  echo "Refusing to overwrite. Delete/rename it first."
  exit 1
fi

# ------------------------------------------------------------
# Optional: override CPU thread usage from HB_THREADS env
# (HB_THREADS is set in jobs.py based on the Settings page)
#
# If HB_THREADS is a positive integer, we build:
#   HB_THREAD_OPTS="--encopts threads=<N>"
#
# This is then included in the HandBrakeCLI calls below.
# If HB_THREADS is unset/0/invalid, HB_THREAD_OPTS stays empty.
# ------------------------------------------------------------
HB_THREAD_OPTS=""
if [ -n "$HB_THREADS" ]; then
  # Only treat HB_THREADS as valid if it looks like a positive integer
  case "$HB_THREADS" in
    *[!0-9]*)
      echo "INFO: Ignoring non-numeric HB_THREADS value: $HB_THREADS" ;;
    *)
      if [ "$HB_THREADS" -gt 0 ] 2>/dev/null; then
        HB_THREAD_OPTS="--encopts threads=$HB_THREADS"
        echo "INFO: Using HB_THREADS=$HB_THREADS (HB_THREAD_OPTS: $HB_THREAD_OPTS)"
      fi ;;
  esac
fi

# ------------------------------------------------------------
# Main encode path:
# - If preset file exists → use preset import + preset name
# - Else → fallback basic x264 settings
# In both cases, we append HB_THREAD_OPTS if present.
# ------------------------------------------------------------
if [ -f "$PRESET_FILE" ]; then
  echo "Using preset file + preset name..."
EXTRA_ARGS="${HB_EXTRA_ARGS:-}"

HandBrakeCLI \
  --preset-import-file "$PRESET_FILE" \
  -Z "$PRESET_NAME" \
  ${HB_THREAD_OPTS} \
  ${EXTRA_ARGS} \
  -i "$SRC" \
  -o "$OUT"

else
  echo "WARNING: Preset file not found, using basic fallback settings..."
  HandBrakeCLI \
    ${HB_THREAD_OPTS} \
    -i "$SRC" \
    -o "$OUT" \
    -e x264 -q 20 -B 160
fi

# ------------------------------------------------------------
# Post-encode checks + clean up
# ------------------------------------------------------------
if [ ! -f "$OUT" ]; then
  echo "ERROR: Encode failed, output file not found."
  exit 1
fi

echo "Encode complete, deleting original: $SRC"
rm -f "$SRC"

echo "Done!"
echo "New file: $OUT"
