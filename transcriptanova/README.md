<div align="center">

# Transcriptanova

**Free open-source speech-to-text for AI agents — Whisper, no API keys.**

A Casanova tool. Agents call it; developers call it — over HTTP or MCP.
Same behaviour on every transport. Runs on your machine, on open-source
[Whisper](https://github.com/openai/whisper), and asks for nothing from a
hosted STT vendor.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-9%20passing-brightgreen.svg)](#testing)
[![MCP](https://img.shields.io/badge/MCP-compatible-8A2BE2.svg)](https://modelcontextprotocol.io/)
[![STT](https://img.shields.io/badge/engine-faster--whisper-brightgreen.svg)](https://github.com/SYSTRAN/faster-whisper)

</div>

---

## Tool

| Tool | Status | What it does |
|---|---|---|
| **`transcribe`** | ✅ scaffold | Speech → text via open-source Whisper — segments, language detect, optional English translate |

Agents and IDEs discover it the same way as the hub's web tools: `GET /schemas`
for an LLM `tools` array, or MCP tool listing over stdio.

---

## Why

Hosted speech-to-text is usually a metered API pointed at someone else's GPU.
This is the same kind of tool — same shapes agents already expect — running
entirely on your own machine.

|  | Hosted STT | Here |
|---|---|---|
| **Keys** | Vendor API key, billing, quotas | None — weights download once, then offline |
| **Engine** | Opaque cloud model | Open-source Whisper (`faster-whisper` by default) |
| **Surface** | Vendor SDK | HTTP tool endpoints **and** MCP — one `Toolset` |
| **Cost per call** | Metered | Your CPU or GPU |

The interesting part isn't wrapping Whisper. It's that **a transcription tool
is a compute primitive pointed at caller-chosen audio**, and the defaults have
to be boringly safe: loopback bind, size caps, URL fetch off until you turn it
on on purpose.

---

## Quick start

```bash
cd transcriptanova
docker compose up -d --build
```

The Whisper model downloads **automatically on first boot** — the container
awaits the download before it reports healthy, and the weights land in the
`models` volume, so it happens **once** and survives image rebuilds. On CPU,
the default `base` model is ~140 MB; a first `docker compose up` therefore
takes a minute or two before `/health` passes.

To pre-download (or just verify the weights are reachable) without starting
the service:

```bash
docker compose run --rm transcriptanova python -m transcriptanova.prefetch
```

```bash
docker compose ps        # STATUS shows "healthy" once the model is loaded
curl localhost:8100/health
```

> **The model lives in the volume, not the image.** `TN_DOWNLOAD_ROOT`
> (`/data/models`) is a mounted volume, so a model baked into the image at that
> path would be shadowed by the mount at runtime. Downloading into the volume
> is what makes it a one-time cost.

**Upload** — preferred for clients and large files:

```bash
curl -X POST localhost:8100/transcribe/upload \
  -F file=@meeting.m4a \
  -F language=en
```

**JSON** — path already on the server:

```bash
curl -X POST localhost:8100/transcribe \
  -H 'content-type: application/json' \
  -d '{"audio_path":"/data/sample.wav","timestamps":true}'
```

As an MCP server over stdio:

```bash
pip install -e ".[service,mcp]"
python -m transcriptanova.mcp_server
```

---

## Architecture

```
       ┌──────────────┐        ┌──────────────┐
       │ HTTP service │        │  MCP server  │      two transports,
       │  (FastAPI)   │        │   (stdio)    │      one behaviour
       └───────┬──────┘        └──────┬───────┘
               └───────────┬──────────┘
                     ┌─────▼──────┐
                     │  Toolset   │  schema · resolve source · envelope
                     └─────┬──────┘
                           │
                     ┌─────▼──────────┐
                     │ WhisperEngine  │  faster-whisper (default)
                     │                │  openai-whisper (optional)
                     └────────────────┘
```

| Module | Role |
|---|---|
| [`config.py`](src/transcriptanova/config.py) | Env-driven model, device, limits (`TN_*`) |
| [`engine.py`](src/transcriptanova/engine.py) | Whisper backends behind one protocol |
| [`tools.py`](src/transcriptanova/tools.py) | Shared layer both front ends call |
| [`service.py`](src/transcriptanova/service.py) | FastAPI HTTP |
| [`mcp_server.py`](src/transcriptanova/mcp_server.py) | MCP stdio / HTTP |

---

## Requirements

No third-party STT API. Everything below is open source.

| Need | Notes |
|---|---|
| **Python 3.11+** | See [`pyproject.toml`](pyproject.toml) / [`requirements.txt`](requirements.txt) |
| **faster-whisper** | Default engine (CTranslate2, MIT) |
| **ffmpeg** | System package — decodes mp3, m4a, webm, mp4, … |
| **CPU or CUDA GPU** | CPU is fine for `base` / `small`; GPU for `medium` / `large-v3` |
| **Disk** | Model weights under `TN_DOWNLOAD_ROOT` (`base` ≈ 140 MB, `large-v3` ≈ 3 GB) |

Optional alternate backend: `pip install '.[openai-whisper]'` and
`TN_BACKEND=openai-whisper`.

| Model | Size class | Typical use |
|---|---|---|
| `tiny` / `base` | small | Agent tooling, voice notes |
| `small` / `medium` | medium | Meetings, interviews |
| `large-v3` / `distil-large-v3` | large | Highest accuracy / speed trade-off |

Before bringing a shared host online:

```bash
bash scripts/preflight.sh
```

Read-only — surveys disk, memory, ffmpeg, NVIDIA, and port 8100. Changes nothing.

---

## API

| Endpoint | Purpose |
|---|---|
| `POST /transcribe` | JSON: `audio_path` / `audio_url` / `audio_base64` |
| `POST /transcribe/upload` | Multipart file upload |
| `GET /schemas` | Tool definitions, ready for an LLM `tools` array |
| `GET /health` | Liveness + engine info |

Errors come back in the response body, not as HTTP status codes — the caller
is an agent loop, and "file too large" is a result to reason about, not a
transport failure. Every response carries the same keys whether it succeeded
or failed.

```json
{
  "text": "…",
  "language": "en",
  "language_probability": 0.98,
  "duration": 12.4,
  "segments": [{"id": 0, "start": 0.0, "end": 2.1, "text": "…"}],
  "model": "base",
  "backend": "faster-whisper",
  "task": "transcribe",
  "source": "meeting.m4a",
  "error": null
}
```

Provide **exactly one** audio source per call: `audio_path`, `audio_url`,
`audio_base64`, or a multipart upload.

---

## Configuration

All via environment variable.

| Variable | Default | Notes |
|---|---|---|
| `TN_BACKEND` | `faster-whisper` | or `openai-whisper` |
| `TN_MODEL` | `base` | See model table above |
| `TN_DEVICE` | `auto` | `cpu` / `cuda` / `auto` |
| `TN_COMPUTE_TYPE` | `default` | `int8` on CPU, `float16` on GPU when default |
| `TN_DOWNLOAD_ROOT` | `./models` | Weight cache |
| `TN_MAX_BYTES` | `26214400` | 25 MiB upload / path cap |
| `TN_TIMEOUT` | `600` | Per-job ceiling (seconds) |
| `TN_LANGUAGE` | _(empty)_ | Force language; empty = auto-detect |
| `TN_BEAM_SIZE` | `5` | Decoder beam |
| `TN_VAD_FILTER` | `true` | Drop long silences (faster-whisper) |
| `TN_ALLOW_URL_FETCH` | `false` | Enable `audio_url` only on trusted nets |
| `TN_PORT` | `8100` | Published port (loopback only) |

---

## Security

**Do not publish the service port without auth in front of it.** Anyone who can
reach it can spend your CPU or GPU on arbitrary audio. The compose file binds
to loopback.

`TN_ALLOW_URL_FETCH` stays **off** by default. Turning it on without an SSRF
perimeter makes the service an outbound fetch proxy — do not do that on a
public host. Prefer upload or a local `audio_path`.

Temporary uploads land under `TMPDIR` and are deleted after each job.

---

## MCP

Cursor / Claude Desktop sketch:

```json
{
  "mcpServers": {
    "transcriptanova": {
      "command": "python",
      "args": ["-m", "transcriptanova.mcp_server"],
      "cwd": "/path/to/Casanova/transcriptanova",
      "env": {
        "TN_MODEL": "base",
        "TN_DEVICE": "cpu"
      }
    }
  }
}
```

---

## Testing

```bash
pytest -q
```

**9 tests.** Schema shape, config, path / base64 resolution, size caps, URL-fetch
default-off, and the stable error envelope — no Whisper weights required.

Live GPU / CPU smoke tests wait on a host with the model downloaded.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

Whisper weights and faster-whisper are MIT. No third-party STT API required.

Copyright 2026 Lucas D Marshall (Kaung Myat San).
