#!/usr/bin/env bash
# Read-only survey before bringing CasaOCR up on a shared host.
set -euo pipefail

echo "== CasaOCR preflight =="
echo

echo "-- disk --"
df -h . 2>/dev/null || true
echo

echo "-- python --"
python3 --version 2>/dev/null || true
echo

echo "-- system deps --"
if command -v tesseract >/dev/null 2>&1; then
  tesseract --version 2>&1 | head -n 1
else
  echo "tesseract: NOT FOUND (needed only for the tesseract engine)"
fi
if command -v pdftoppm >/dev/null 2>&1; then
  echo "poppler: $(pdftoppm -v 2>&1 | head -n 1)"
else
  echo "poppler (pdftoppm): NOT FOUND (needed for scanned PDFs)"
fi
echo

echo "-- python deps (import check) --"
python3 - <<'PY' 2>/dev/null || echo "some imports missing — pip install -r requirements.txt"
import importlib
for mod in ("PIL", "numpy", "cv2", "pdf2image", "casanova_core", "paddleocr"):
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
  echo "port 8400 listeners:"
  ss -ltn 'sport = :8400' 2>/dev/null || netstat -ltn 2>/dev/null | grep 8400 || echo "(none)"
else
  echo "docker: NOT FOUND"
fi
echo

echo "Preflight finished (read-only; nothing changed)."
