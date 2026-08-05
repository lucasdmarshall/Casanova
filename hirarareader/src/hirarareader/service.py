"""HTTP front end.

    uvicorn hirarareader.service:app --host 0.0.0.0 --port 8500

Same Toolset as the MCP server, so the two cannot drift apart in behaviour.

Bind this to localhost or keep it behind your own auth. Anyone who can reach it
can spend your CPU on arbitrary documents, and — if you enable file_path — read
files as this process.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, File, Form, UploadFile
from pydantic import BaseModel

from .tools import Toolset

log = logging.getLogger("hirarareader.service")

_toolset = Toolset.from_env()

app = FastAPI(title="hirarareader", version="0.1.0")


class ReadRequest(BaseModel):
    """JSON body for path / URL / base64 reads."""

    file_path: str | None = None
    file_url: str | None = None
    file_base64: str | None = None
    filename: str | None = None


@app.get("/health")
async def health() -> dict:
    return _toolset.health()


@app.get("/schemas")
async def schemas() -> dict:
    """Tool definition, ready to drop into an LLM `tools` array."""
    return {"tools": _toolset.schemas()}


@app.post("/office_read")
async def office_read(request: ReadRequest) -> dict:
    # Errors come back in the body, not as HTTP status codes: the caller is an
    # agent loop, and "unrecognized document" is a result to reason about.
    return await _toolset.read(
        file_path=request.file_path,
        file_url=request.file_url,
        file_base64=request.file_base64,
        filename=request.filename,
    )


@app.post("/office_read/upload")
async def office_read_upload(file: UploadFile = File(...)) -> dict:
    """Multipart upload — preferred for large documents from clients/devs."""
    data = await file.read()
    return await _toolset.read(file_bytes=data, filename=file.filename)
