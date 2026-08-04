FROM python:3.13-slim

WORKDIR /app

COPY casanovacode/pyproject.toml casanovacode/README.md \
     casanovacode/LICENSE casanovacode/NOTICE casanovacode/requirements.txt ./
COPY casanovacode/src ./src

RUN pip install --no-cache-dir . "uvicorn[standard]" "fastapi" "mcp"

# NOTE: this service is intentionally NOT run as an unprivileged user, and the
# container is given access to the host's Docker socket (see docker-compose.yml).
# Driving the daemon is root-equivalent on the host — that is inherent to a
# Docker-isolated executor, not an oversight. The mitigation is operational:
# bind the service to loopback, put auth in front, never expose it. The code it
# runs is what gets sandboxed (sibling containers), not this process.

ENV CCODE_ALLOW_NETWORK=false \
    PYTHONUNBUFFERED=1

EXPOSE 8300

CMD ["uvicorn", "casanovacode.service:app", "--host", "0.0.0.0", "--port", "8300"]
