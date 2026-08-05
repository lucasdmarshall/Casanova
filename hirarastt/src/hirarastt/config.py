"""Runtime configuration for HiraraSTT.

Everything is overridable by environment variable so the same image can run
a tiny ``tiny`` model on a laptop or ``large-v3`` on a GPU box.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return raw.strip().lower() in {"1", "true", "yes", "on"} if raw else default


# Whisper model sizes shipped by OpenAI / faster-whisper.
WHISPER_MODELS = (
    "tiny",
    "tiny.en",
    "base",
    "base.en",
    "small",
    "small.en",
    "medium",
    "medium.en",
    "large-v2",
    "large-v3",
    "distil-large-v3",
)


@dataclass(frozen=True)
class TranscribeConfig:
    """Whisper runtime knobs.

    Defaults favour a self-hosted agent tool: free, offline after the first
    model download, and usable on CPU. Point ``TN_DEVICE=cuda`` (and usually
    ``TN_COMPUTE_TYPE=float16``) when a GPU is available.
    """

    # Backend: faster-whisper (default) or openai-whisper.
    backend: str = "faster-whisper"

    # Model id — see WHISPER_MODELS. ``base`` is a sensible default for
    # agent tooling; bump to ``small``/``medium``/``large-v3`` for accuracy.
    model: str = "base"

    # cpu | cuda | auto
    device: str = "auto"

    # Faster-whisper compute type. int8 is the usual CPU choice; float16 for GPU.
    compute_type: str = "default"

    # Directory for downloaded model weights (shared across restarts).
    download_root: str = "./models"

    # Max decoded audio/file size accepted from callers.
    max_bytes: int = 25 * 1024 * 1024

    # Cap how long we will spend on one transcription (seconds).
    timeout: float = 600.0

    # Default language. Empty / None = auto-detect.
    language: str | None = None

    # Beam size for decoding (higher = slower, sometimes more accurate).
    beam_size: int = 5

    # VAD filter drops long silences before decoding (faster-whisper only).
    vad_filter: bool = True

    # Allow fetching audio from http(s) URLs. Off by default. When on, the
    # fetch goes through hirara-core's safe_download — resolve-then-pin,
    # every redirect hop re-validated, streamed and size-capped — so enabling
    # it does not open an SSRF hole the way a bare httpx.get would.
    allow_url_fetch: bool = False
    url_timeout: float = 30.0

    # Allow transcribing a local file the caller names by path. This is the
    # primary use of the tool run locally (MCP over stdio, or a loopback HTTP
    # service): "transcribe /home/me/recording.mp3". But over a network-exposed
    # HTTP service, audio_path lets any caller name any file on the box, so set
    # TN_ALLOW_LOCAL_PATH=false there and use upload / base64 instead.
    allow_local_path: bool = True

    @classmethod
    def from_env(cls) -> "TranscribeConfig":
        language = os.getenv("TN_LANGUAGE", "").strip() or None
        compute = os.getenv("TN_COMPUTE_TYPE", cls.compute_type).strip()
        backend = os.getenv("TN_BACKEND", cls.backend).strip().lower()
        if backend not in {"faster-whisper", "openai-whisper"}:
            backend = cls.backend
        return cls(
            backend=backend,
            model=os.getenv("TN_MODEL", cls.model).strip() or cls.model,
            device=os.getenv("TN_DEVICE", cls.device).strip() or cls.device,
            compute_type=compute or cls.compute_type,
            download_root=os.getenv("TN_DOWNLOAD_ROOT", cls.download_root),
            max_bytes=_env_int("TN_MAX_BYTES", cls.max_bytes),
            timeout=_env_float("TN_TIMEOUT", cls.timeout),
            language=language,
            beam_size=_env_int("TN_BEAM_SIZE", cls.beam_size),
            vad_filter=_env_bool("TN_VAD_FILTER", cls.vad_filter),
            allow_url_fetch=_env_bool("TN_ALLOW_URL_FETCH", cls.allow_url_fetch),
            url_timeout=_env_float("TN_URL_TIMEOUT", cls.url_timeout),
            allow_local_path=_env_bool("TN_ALLOW_LOCAL_PATH", cls.allow_local_path),
        )
