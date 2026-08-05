FROM python:3.13-slim

WORKDIR /app

COPY casanova-hub/pyproject.toml casanova-hub/README.md \
     casanova-hub/LICENSE casanova-hub/NOTICE casanova-hub/requirements.txt ./
COPY casanova-hub/src ./src

RUN pip install --no-cache-dir . "mcp"

RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["uvicorn", "casanova_hub.service:app", "--host", "0.0.0.0", "--port", "8080"]
