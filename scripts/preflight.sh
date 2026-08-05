#!/usr/bin/env bash
# Read-only survey of the target host. Changes nothing.
#
# Run this before deploying onto a server with live workloads. Every command
# below is an inspection: no pulls, no builds, no starts, no writes.
#
#   bash scripts/preflight.sh

set -uo pipefail

WT_PORT="${WT_PORT:-8000}"

hr() { printf '\n=== %s ===\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

hr "Host"
uname -a
if [ -r /etc/os-release ]; then . /etc/os-release; echo "distro: ${PRETTY_NAME:-unknown}"; fi
echo "cpus: $(nproc 2>/dev/null || echo '?')"
free -h 2>/dev/null | awk 'NR<=2'

hr "Disk"
df -h / /var/lib/docker 2>/dev/null | sort -u

hr "Docker"
if have docker; then
    docker --version
    docker compose version 2>/dev/null || echo "compose plugin: MISSING (need 'docker compose', not 'docker-compose')"
    if ! docker info >/dev/null 2>&1; then
        echo "WARNING: cannot talk to the docker daemon as $(whoami)."
        echo "         Either the daemon is down or this user is not in the docker group."
    fi
else
    echo "docker: NOT INSTALLED"
fi

hr "Running containers (do not disturb)"
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null \
    || echo "unavailable"

hr "Existing compose projects"
docker ps -a --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null \
    | grep -v '^$' | sort -u || echo "none"

# A project already called hirara-web would be adopted by our compose file.
if docker ps -a --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null \
    | grep -qx 'hirara-web'; then
    echo "WARNING: a compose project named 'hirara-web' already exists here."
    echo "         Our deploy would adopt its containers. Rename ours before proceeding."
fi

hr "Port ${WT_PORT} availability"
if have ss; then
    if ss -ltnp 2>/dev/null | grep -q ":${WT_PORT}\b"; then
        echo "IN USE:"; ss -ltnp 2>/dev/null | grep ":${WT_PORT}\b"
        echo "-> set WT_PORT to something free before deploying"
    else
        echo "port ${WT_PORT} is free"
    fi
else
    echo "ss not available; check manually"
fi

hr "Listening services (context)"
ss -ltn 2>/dev/null | awk 'NR==1 || NR<=15' || echo unavailable

hr "Egress check"
# Confirms the host can reach the engines SearXNG will query. A failure here
# means the free-search plan is dead before we start.
for host in duckduckgo.com www.mojeek.com en.wikipedia.org search.brave.com; do
    if have curl; then
        code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "https://${host}" 2>/dev/null)
        printf '  %-22s HTTP %s\n' "$host" "${code:-FAILED}"
    fi
done

hr "Outbound IP"
# Datacenter ranges are what trigger engine CAPTCHAs. Worth knowing up front.
if have curl; then
    curl -s --max-time 8 https://api.ipify.org 2>/dev/null || echo "could not determine"
    echo
fi

hr "Summary"
echo "Nothing was modified. Review the warnings above before deploying."
