#!/usr/bin/env bash
# Read-only survey before bringing Hirarapdf up on a shared host.
set -euo pipefail

echo "== Hirarapdf preflight =="
echo

echo "-- disk --"
df -h . 2>/dev/null || true
echo

echo "-- python --"
python3 --version 2>/dev/null || true
echo

echo "-- deps (import check) --"
python3 - <<'PY' 2>/dev/null || echo "some imports missing — pip install -r requirements.txt"
import importlib
for mod in ("pypdf", "reportlab", "hirara_core"):
    try:
        importlib.import_module(mod)
        print(f"{mod}: ok")
    except Exception as exc:
        print(f"{mod}: MISSING ({exc})")
PY
echo

echo "-- docker --"
if command -v docker >/dev/null 2>&1; then
  docker version --format '{{.Server.Version}}' 2>/dev/null || docker version | head -n 5
  echo "port 8200 listeners:"
  ss -ltn 'sport = :8200' 2>/dev/null || netstat -ltn 2>/dev/null | grep 8200 || echo "(none)"
else
  echo "docker: NOT FOUND"
fi
echo

echo "Preflight finished (read-only; nothing changed)."
