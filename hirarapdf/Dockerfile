FROM python:3.13-slim

WORKDIR /app

# Build context is the repo root (see docker-compose.yml), so paths are
# repo-relative. Install the shared SSRF guard first, so the tool install
# below sees hirara-core already satisfied instead of hitting PyPI.
COPY hirara-core ./hirara-core
RUN pip install --no-cache-dir ./hirara-core

COPY hirarapdf/pyproject.toml hirarapdf/README.md \
     hirarapdf/LICENSE hirarapdf/NOTICE hirarapdf/requirements.txt ./
COPY hirarapdf/src ./src

RUN pip install --no-cache-dir . "uvicorn[standard]" "fastapi" "python-multipart" "mcp"

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data/output /data/tmp \
    && chown -R app:app /data /app
USER app

ENV CPDF_ALLOW_LOCAL_PATH=false \
    CPDF_ALLOW_URL_FETCH=false \
    PYTHONUNBUFFERED=1 \
    TMPDIR=/data/tmp

EXPOSE 8200

CMD ["uvicorn", "hirarapdf.service:app", "--host", "0.0.0.0", "--port", "8200"]
