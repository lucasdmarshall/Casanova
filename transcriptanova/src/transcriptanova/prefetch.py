"""Download the configured Whisper model, now, into the model directory.

    python -m transcriptanova.prefetch

Run this to pay the one-time download cost up front instead of on the first
transcription. Weights land in ``TN_DOWNLOAD_ROOT`` (``/data/models`` in the
container) — a persistent volume, so the download happens once and survives
image rebuilds. Baking the model into the image instead would not work: the
volume mount shadows whatever is baked at that path.

Exits non-zero and says why if the download fails, so a deploy that cannot
reach the weights fails loudly rather than starting a service that errors on
every call.
"""

from __future__ import annotations

import logging
import sys
import time

from .config import TranscribeConfig
from .engine import EngineError, build_engine

log = logging.getLogger("transcriptanova.prefetch")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    config = TranscribeConfig.from_env()
    log.info(
        "Prefetching model=%s backend=%s device=%s into %s",
        config.model,
        config.backend,
        config.device,
        config.download_root,
    )

    engine = build_engine(config)
    started = time.monotonic()
    try:
        engine.ensure_loaded()
    except EngineError as exc:
        log.error("prefetch failed: %s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001 — surface the real cause and fail
        log.error("prefetch failed: %s: %s", type(exc).__name__, exc)
        return 1

    elapsed = time.monotonic() - started
    log.info("model ready in %.1fs — %s", elapsed, engine.info())
    return 0


if __name__ == "__main__":
    sys.exit(main())
