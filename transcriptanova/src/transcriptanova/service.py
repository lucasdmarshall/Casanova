"""HTTP front end.

    uvicorn transcriptanova.service:app --host 0.0.0.0 --port 8100

Same Toolset as the MCP server, so the two cannot drift apart in behaviour.

Bind this to localhost or keep it behind your own auth. Anyone who can reach
it can spend your CPU/GPU on arbitrary audio.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, UploadFile
from pydantic import BaseModel, Field

from .tools import TRANSCRIBE_SCHEMA, Toolset

_toolset = Toolset.from_env()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Eager-load the Whisper model at boot so the first agent call is not
    # paying for a multi-hundred-MB download. Failures are non-fatal here —
    # /health still reports, and the first transcribe surfaces the error.
    try:
        if hasattr(_toolset.engine, "_load"):
            _toolset.engine._load()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    yield


app = FastAPI(title="transcriptanova", version="0.1.0", lifespan=lifespan)


class TranscribeRequest(BaseModel):
    """JSON body for path / URL / base64 transcription."""

    audio_path: str | None = None
    audio_url: str | None = None
    audio_base64: str | None = None
    filename: str | None = None
    language: str | None = None
    task: str = Field("transcribe", pattern="^(transcribe|translate)$")
    timestamps: bool = True
    prompt: str | None = None


@app.get("/health")
async def health() -> dict:
    return _toolset.health()


@app.get("/schemas")
async def schemas() -> dict:
    """Tool definitions, ready to drop into an LLM `tools` array."""
    return {"tools": _toolset.schemas()}


@app.post("/transcribe")
async def transcribe_json(request: TranscribeRequest) -> dict:
    # Errors come back in the body rather than as HTTP status codes: the
    # caller is an agent loop, and "file too large" is a result to reason
    # about, not a transport failure.
    return await _toolset.transcribe(
        audio_path=request.audio_path,
        audio_url=request.audio_url,
        audio_base64=request.audio_base64,
        filename=request.filename,
        language=request.language,
        task=request.task,
        timestamps=request.timestamps,
        prompt=request.prompt,
    )


@app.post("/transcribe/upload")
async def transcribe_upload(
    file: UploadFile = File(...),
    language: str | None = Form(None),
    task: str = Form("transcribe"),
    timestamps: bool = Form(True),
    prompt: str | None = Form(None),
) -> dict:
    """Multipart upload — preferred for large audio from clients/devs."""
    if task not in {"transcribe", "translate"}:
        return {
            "text": None,
            "language": None,
            "language_probability": None,
            "duration": None,
            "segments": [],
            "model": None,
            "backend": None,
            "task": task,
            "source": file.filename,
            "error": "task must be 'transcribe' or 'translate'",
        }
    data = await file.read()
    return await _toolset.transcribe(
        audio_bytes=data,
        filename=file.filename,
        language=language,
        task=task,
        timestamps=timestamps,
        prompt=prompt,
    )
