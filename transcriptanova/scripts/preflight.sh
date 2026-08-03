#!/usr/bin/env bash
# Read-only survey before bringing Transcriptanova up on a shared host.
set -euo pipefail

echo "== Transcriptanova preflight =="
echo

echo "-- disk --"
df -h . 2>/dev/null || true
echo

echo "-- memory --"
free -h 2>/dev/null || true
echo

echo "-- ffmpeg --"
if command -v ffmpeg >/dev/null 2>&1; then
  ffmpeg -version | head -n 1
else
  echo "ffmpeg: NOT FOUND (required for non-wav audio)"
fi
echo

echo "-- nvidia (optional) --"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi -L 2>/dev/null || nvidia-smi | head -n 15
else
  echo "nvidia-smi: not present — CPU mode is fine for TN_MODEL=base/small"
fi
echo

echo "-- docker --"
if command -v docker >/dev/null 2>&1; then
  docker version --format '{{.Server.Version}}' 2>/dev/null || docker version | head -n 5
  echo "port 8100 listeners:"
  ss -ltn 'sport = :8100' 2>/dev/null || netstat -ltn 2>/dev/null | grep 8100 || echo "(none)"
else
  echo "docker: NOT FOUND"
fi
echo

echo "-- python --"
python3 --version 2>/dev/null || true
echo

echo "Preflight finished (read-only; nothing changed)."
