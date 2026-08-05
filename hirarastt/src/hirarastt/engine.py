"""Whisper backend — open-source STT, no API keys.

Default engine is `faster-whisper` (CTranslate2). Optional `openai-whisper`
is available behind the same protocol so callers never care which backend
is loaded.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from .config import TranscribeConfig

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Segment:
    """One timed span of speech."""

    id: int
    start: float
    end: float
    text: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Transcription:
    """JSON-ready transcription result."""

    text: str
    language: str | None = None
    language_probability: float | None = None
    duration: float | None = None
    segments: list[Segment] = field(default_factory=list)
    model: str | None = None
    backend: str | None = None
    task: str = "transcribe"

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "language": self.language,
            "language_probability": self.language_probability,
            "duration": self.duration,
            "segments": [s.as_dict() for s in self.segments],
            "model": self.model,
            "backend": self.backend,
            "task": self.task,
        }


class WhisperEngine(Protocol):
    """Swappable STT backend."""

    async def transcribe(
        self,
        audio_path: str | Path,
        *,
        language: str | None = None,
        task: str = "transcribe",
        timestamps: bool = True,
        initial_prompt: str | None = None,
    ) -> Transcription: ...

    def info(self) -> dict: ...

    def ensure_loaded(self) -> None:
        """Download (if needed) and load the model weights now.

        Callers use this to pay the one-time download cost up front — at
        container boot or via the prefetch command — instead of on the first
        transcription. Idempotent; raises :class:`EngineError` on failure.
        """
        ...


class EngineError(RuntimeError):
    """Raised when a backend cannot load or decode."""


class FasterWhisperEngine:
    """Production default — free, local, MIT-licensed via faster-whisper."""

    def __init__(self, config: TranscribeConfig) -> None:
        self.config = config
        self._model = None
        self._lock = threading.Lock()

    def info(self) -> dict:
        return {
            "backend": "faster-whisper",
            "model": self.config.model,
            "device": self.config.device,
            "compute_type": self.config.compute_type,
            "loaded": self._model is not None,
        }

    def ensure_loaded(self) -> None:
        self._load()

    def _load(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise EngineError(
                    "faster-whisper is not installed. "
                    "pip install 'hirarastt' or pip install faster-whisper"
                ) from exc

            device = self.config.device
            compute_type = self.config.compute_type
            if compute_type == "default":
                compute_type = "float16" if device == "cuda" else "int8"

            Path(self.config.download_root).mkdir(parents=True, exist_ok=True)
            log.info(
                "Loading faster-whisper model=%s device=%s compute_type=%s",
                self.config.model,
                device,
                compute_type,
            )
            self._model = WhisperModel(
                self.config.model,
                device=device,
                compute_type=compute_type,
                download_root=self.config.download_root,
            )
            return self._model

    def _transcribe_sync(
        self,
        audio_path: str,
        *,
        language: str | None,
        task: str,
        timestamps: bool,
        initial_prompt: str | None,
    ) -> Transcription:
        model = self._load()
        lang = language if language is not None else self.config.language
        segments_iter, info = model.transcribe(
            audio_path,
            language=lang,
            task=task,
            beam_size=self.config.beam_size,
            vad_filter=self.config.vad_filter,
            initial_prompt=initial_prompt,
            word_timestamps=False,
        )

        segments: list[Segment] = []
        texts: list[str] = []
        for i, seg in enumerate(segments_iter):
            text = (seg.text or "").strip()
            texts.append(text)
            if timestamps:
                segments.append(
                    Segment(id=i, start=float(seg.start), end=float(seg.end), text=text)
                )

        return Transcription(
            text=" ".join(t for t in texts if t).strip(),
            language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", None),
            duration=getattr(info, "duration", None),
            segments=segments,
            model=self.config.model,
            backend="faster-whisper",
            task=task,
        )

    async def transcribe(
        self,
        audio_path: str | Path,
        *,
        language: str | None = None,
        task: str = "transcribe",
        timestamps: bool = True,
        initial_prompt: str | None = None,
    ) -> Transcription:
        path = str(audio_path)
        if not os.path.isfile(path):
            raise EngineError(f"audio file not found: {path}")
        if task not in {"transcribe", "translate"}:
            raise EngineError(f"unsupported task: {task}")

        return await asyncio.to_thread(
            self._transcribe_sync,
            path,
            language=language,
            task=task,
            timestamps=timestamps,
            initial_prompt=initial_prompt,
        )


class OpenAIWhisperEngine:
    """Optional alternate backend using the original openai-whisper package."""

    def __init__(self, config: TranscribeConfig) -> None:
        self.config = config
        self._model = None
        self._lock = threading.Lock()

    def info(self) -> dict:
        return {
            "backend": "openai-whisper",
            "model": self.config.model,
            "device": self.config.device,
            "loaded": self._model is not None,
        }

    def ensure_loaded(self) -> None:
        self._load()

    def _load(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                import whisper
            except ImportError as exc:
                raise EngineError(
                    "openai-whisper is not installed. "
                    "pip install 'hirarastt[openai-whisper]'"
                ) from exc

            device = None if self.config.device == "auto" else self.config.device
            Path(self.config.download_root).mkdir(parents=True, exist_ok=True)
            log.info("Loading openai-whisper model=%s device=%s", self.config.model, device)
            self._model = whisper.load_model(
                self.config.model,
                device=device,
                download_root=self.config.download_root,
            )
            return self._model

    def _transcribe_sync(
        self,
        audio_path: str,
        *,
        language: str | None,
        task: str,
        timestamps: bool,
        initial_prompt: str | None,
    ) -> Transcription:
        model = self._load()
        lang = language if language is not None else self.config.language
        result = model.transcribe(
            audio_path,
            language=lang,
            task=task,
            initial_prompt=initial_prompt,
            verbose=False,
        )
        segments: list[Segment] = []
        if timestamps:
            for i, seg in enumerate(result.get("segments") or []):
                segments.append(
                    Segment(
                        id=i,
                        start=float(seg.get("start", 0.0)),
                        end=float(seg.get("end", 0.0)),
                        text=str(seg.get("text", "")).strip(),
                    )
                )
        return Transcription(
            text=str(result.get("text", "")).strip(),
            language=result.get("language"),
            language_probability=None,
            duration=None,
            segments=segments,
            model=self.config.model,
            backend="openai-whisper",
            task=task,
        )

    async def transcribe(
        self,
        audio_path: str | Path,
        *,
        language: str | None = None,
        task: str = "transcribe",
        timestamps: bool = True,
        initial_prompt: str | None = None,
    ) -> Transcription:
        path = str(audio_path)
        if not os.path.isfile(path):
            raise EngineError(f"audio file not found: {path}")
        if task not in {"transcribe", "translate"}:
            raise EngineError(f"unsupported task: {task}")
        return await asyncio.to_thread(
            self._transcribe_sync,
            path,
            language=language,
            task=task,
            timestamps=timestamps,
            initial_prompt=initial_prompt,
        )


def build_engine(config: TranscribeConfig | None = None) -> WhisperEngine:
    """Construct the configured backend."""
    cfg = config or TranscribeConfig.from_env()
    if cfg.backend == "openai-whisper":
        return OpenAIWhisperEngine(cfg)
    return FasterWhisperEngine(cfg)


def write_temp_audio(data: bytes, *, suffix: str = ".wav") -> Path:
    """Persist uploaded/base64 audio to a temp file the engine can open."""
    fd, name = tempfile.mkstemp(prefix="tn-", suffix=suffix)
    path = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


__all__ = [
    "EngineError",
    "FasterWhisperEngine",
    "OpenAIWhisperEngine",
    "Segment",
    "Transcription",
    "WhisperEngine",
    "build_engine",
    "write_temp_audio",
]
