FROM python:3.13-slim

WORKDIR /app

# Build context is the repo root (see docker-compose.yml). Install the shared
# SSRF guard first so the tool install sees casanova-core already satisfied.
COPY casanova-core ./casanova-core
RUN pip install --no-cache-dir ./casanova-core

COPY casareader/pyproject.toml casareader/README.md \
     casareader/LICENSE casareader/NOTICE casareader/requirements.txt ./
COPY casareader/src ./src

# Pure-Python readers (python-docx/pptx/openpyxl) + the HTTP + MCP front ends.
RUN pip install --no-cache-dir . "uvicorn[standard]" "fastapi" "python-multipart" "mcp"

RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

ENV CRDR_ALLOW_LOCAL_PATH=false \
    CRDR_ALLOW_URL_FETCH=false \
    PYTHONUNBUFFERED=1

EXPOSE 8500

CMD ["uvicorn", "casareader.service:app", "--host", "0.0.0.0", "--port", "8500"]
