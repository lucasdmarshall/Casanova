FROM python:3.13-slim

WORKDIR /app

# Build context is the repo root (see docker-compose.yml), so paths are
# repo-relative. Install the shared SSRF guard first, so the tool install
# below sees casanova-core already satisfied instead of hitting PyPI.
COPY casanova-core ./casanova-core
RUN pip install --no-cache-dir ./casanova-core

COPY casanovapdf/pyproject.toml casanovapdf/README.md \
     casanovapdf/LICENSE casanovapdf/NOTICE casanovapdf/requirements.txt ./
COPY casanovapdf/src ./src

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

CMD ["uvicorn", "casanovapdf.service:app", "--host", "0.0.0.0", "--port", "8200"]
