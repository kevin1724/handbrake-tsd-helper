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

PRESET_FILE="${HB_PRESET_FILE:-/presets/my-presets.json}"
PRESET_NAME="${HB_PRESET_NAME:-MyPresetName}"

echo "=== HandBrake one-shot encode ==="
echo "Source : $SRC"
echo "Target : $OUT"
echo "Suffix : -$SUFFIX"
echo "Preset file : $PRESET_FILE"
echo "Preset name : $PRESET_NAME"
echo "=================================="

if [ -f "$OUT" ]; then
  echo "ERROR: Output already exists: $OUT"
  echo "Refusing to overwrite. Delete/rename it first."
  exit 1
fi

if [ -f "$PRESET_FILE" ]; then
  echo "Using preset file + preset name..."
  HandBrakeCLI \
    --preset-import-file "$PRESET_FILE" \
    -Z "$PRESET_NAME" \
    -i "$SRC" \
    -o "$OUT"
else
  echo "WARNING: Preset file not found, using basic fallback settings..."
  HandBrakeCLI \
    -i "$SRC" \
    -o "$OUT" \
    -e x264 -q 20 -B 160
fi

if [ ! -f "$OUT" ]; then
  echo "ERROR: Encode failed, output file not found."
  exit 1
fi

echo "Encode complete, deleting original: $SRC"
rm -f "$SRC"

echo "Done!"
echo "New file: $OUT"
