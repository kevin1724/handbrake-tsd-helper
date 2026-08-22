#!/bin/sh
set -u

# Diagnostics are informative at startup because software-only hosts are still
# supported. QSV jobs repeat the same checks and fall back to software decode
# if the render device is unavailable.
/usr/local/bin/bytesqueeze-qsv-preflight startup || \
  echo "[ByteSqueeze] QSV startup preflight unavailable; software jobs remain enabled"

exec "$@"
