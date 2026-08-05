#!/usr/bin/env bash
# Read-only survey before bringing Hiraracode up on a host.
set -euo pipefail

echo "== Hiraracode preflight =="
echo

echo "-- docker --"
if command -v docker >/dev/null 2>&1; then
  docker version --format 'client {{.Client.Version}} / server {{.Server.Version}}' 2>/dev/null \
    || echo "docker present but daemon unreachable"
else
  echo "docker: NOT FOUND — this tool cannot run without a Docker daemon"
fi
echo

echo "-- sandbox images --"
for img in python:3.12-slim node:20-slim bash:5; do
  if docker image inspect "$img" >/dev/null 2>&1; then
    echo "$img: present"
  else
    echo "$img: missing (will be pulled on first use; pre-pull to avoid the delay)"
  fi
done
echo

echo "-- socket --"
if [ -S /var/run/docker.sock ]; then
  echo "/var/run/docker.sock: present"
  echo "  NOTE: mounting this into the service is root-equivalent on the host."
  echo "  Keep the service loopback-bound and behind auth."
else
  echo "/var/run/docker.sock: not found at the default path"
fi
echo

echo "-- port --"
ss -ltn 'sport = :8300' 2>/dev/null || netstat -ltn 2>/dev/null | grep 8300 || echo "port 8300: (free)"
echo

echo "Preflight finished (read-only; nothing changed)."
