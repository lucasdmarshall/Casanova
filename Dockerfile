FROM python:3.13-slim

# lxml (via trafilatura) needs these at build time on slim.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir . "uvicorn[standard]" "fastapi" "mcp"

# Runs unprivileged: this process fetches attacker-chosen URLs for a living.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown -R app:app /data /app
USER app

ENV WT_CACHE_PATH=/data/cache.db \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "web_tools.service:app", "--host", "0.0.0.0", "--port", "8000"]
