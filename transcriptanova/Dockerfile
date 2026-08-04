FROM python:3.13-slim

# faster-whisper needs ffmpeg for non-wav inputs; ctranslate2 wheels cover the rest.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Build context is the repo root (see docker-compose.yml), so paths are
# repo-relative. Install the shared SSRF guard first, so the tool install
# below sees casanova-core already satisfied instead of hitting PyPI.
COPY casanova-core ./casanova-core
RUN pip install --no-cache-dir ./casanova-core

COPY transcriptanova/pyproject.toml transcriptanova/README.md \
     transcriptanova/LICENSE transcriptanova/NOTICE transcriptanova/requirements.txt ./
COPY transcriptanova/src ./src

RUN pip install --no-cache-dir . "uvicorn[standard]" "fastapi" "python-multipart" "mcp"

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data/models /data/tmp \
    && chown -R app:app /data /app
USER app

ENV TN_DOWNLOAD_ROOT=/data/models \
    TN_MODEL=base \
    TN_DEVICE=cpu \
    TN_COMPUTE_TYPE=int8 \
    PYTHONUNBUFFERED=1 \
    TMPDIR=/data/tmp

EXPOSE 8100

CMD ["uvicorn", "transcriptanova.service:app", "--host", "0.0.0.0", "--port", "8100"]
