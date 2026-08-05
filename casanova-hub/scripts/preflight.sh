#!/usr/bin/env bash
# Read-only survey before bringing the Casanova hub up on a shared host.
set -euo pipefail

echo "== Casanova hub preflight =="
echo

echo "-- python --"
python3 --version 2>/dev/null || true
echo

echo "-- docker --"
if command -v docker >/dev/null 2>&1; then
  docker version --format '{{.Server.Version}}' 2>/dev/null || docker version | head -n 5
else
  echo "docker: NOT FOUND (needed for the full stack + execute_code)"
fi
echo

echo "-- hub / tool ports (should be free) --"
for port in 8080 8000 8100 8200 8300 8400 8500; do
  if ss -ltn "sport = :$port" 2>/dev/null | grep -q ":$port"; then
    echo "port $port: IN USE"
  else
    echo "port $port: free"
  fi
done
echo

echo "Preflight finished (read-only; nothing changed)."
