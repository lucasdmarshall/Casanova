# Transcriptanova

**Free, open-source speech-to-text for AI agents — powered by Whisper.**

No API keys. No hosted black box. Agents call it as a tool; developers call it
over HTTP or MCP. Same behaviour on every transport.

Part of [Casanova](../README.md) — the self-hosted tool hub for AI agents.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-compatible-8A2BE2.svg)](https://modelcontextprotocol.io/)
[![STT](https://img.shields.io/badge/STT-faster--whisper-brightgreen.svg)](https://github.com/SYSTRAN/faster-whisper)

---

## Status

Scaffold ready. Whisper engine, tool schema, HTTP service, and MCP server are
wired. Point it at a machine with CPU or GPU when you have server access, then
`docker compose up`.

| Piece | Status |
|---|---|
| Tool schema (`transcribe`) | ✅ |
| faster-whisper backend | ✅ |
| openai-whisper backend (optional) | ✅ |
| HTTP `/transcribe` + `/transcribe/upload` | ✅ |
| MCP stdio / streamable-http | ✅ |
| Docker image + compose | ✅ |
| Live GPU smoke test | ⏳ waiting on server |

---

## Tool

| Tool | What it does |
|---|---|
| **`transcribe`** | Speech → text via open-source Whisper. Optional segment timestamps. `task=translate` for English output. |

Agents and IDEs discover it the same way as the hub's web tools: `GET /schemas`
for an LLM `tools` array, or MCP tool listing over stdio.

---

## Quick start (once the host is ready)

```bash
cd transcriptanova
docker compose up -d --build
curl localhost:8100/health
```

**JSON (path on the server):**

```bash
curl -X POST localhost:8100/transcribe \
  -H 'content-type: application/json' \
  -d '{"audio_path":"/data/sample.wav","timestamps":true}'
```

**Multipart upload (preferred for clients):**

```bash
curl -X POST localhost:8100/transcribe/upload \
  -F file=@meeting.m4a \
  -F language=en
```

**As an MCP server:**

```bash
pip install -e ".[service,mcp]"
python -m transcriptanova.mcp_server
```

Cursor / Claude Desktop MCP config sketch:

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
| [`config.py`](src/transcriptanova/config.py) | Env-driven model / device / limits (`TN_*`) |
| [`engine.py`](src/transcriptanova/engine.py) | Whisper backends behind one protocol |
| [`tools.py`](src/transcriptanova/tools.py) | Shared layer both front ends call |
| [`service.py`](src/transcriptanova/service.py) | FastAPI HTTP |
| [`mcp_server.py`](src/transcriptanova/mcp_server.py) | MCP stdio / HTTP |

---

## Requirements

### Python

See [`requirements.txt`](requirements.txt) and [`pyproject.toml`](pyproject.toml).

| Dependency | Why |
|---|---|
| **faster-whisper** | Default STT engine (CTranslate2, MIT, free) |
| **httpx** | Optional audio URL download |
| **fastapi** + **uvicorn** | HTTP tool service |
| **python-multipart** | `/transcribe/upload` |
| **mcp** | Agent / IDE tool transport |
| **ffmpeg** (system) | Decode mp3/m4a/webm/mp4, etc. |

Optional: `openai-whisper` via `pip install '.[openai-whisper]'` and `TN_BACKEND=openai-whisper`.

### Host

| Resource | Notes |
|---|---|
| **CPU** | Works; use `TN_MODEL=base` or `small`, `TN_COMPUTE_TYPE=int8` |
| **GPU (CUDA)** | Preferred for `medium` / `large-v3`; set `TN_DEVICE=cuda`, `TN_COMPUTE_TYPE=float16` |
| **Disk** | Model weights under `TN_DOWNLOAD_ROOT` (e.g. `base` ≈ 140 MB, `large-v3` ≈ 3 GB) |
| **RAM** | Roughly 1–2× model size on CPU; less headroom needed on GPU |

### Model sizes (Whisper)

| Model | Relative size | Typical use |
|---|---|---|
| `tiny` / `base` | small | Agent tooling, voice notes |
| `small` / `medium` | medium | Meetings, interviews |
| `large-v3` / `distil-large-v3` | large | Highest accuracy / speed trade-off |

---

## Configuration

All via environment variable (`TN_` = Transcriptanova).

| Variable | Default | Notes |
|---|---|---|
| `TN_BACKEND` | `faster-whisper` | or `openai-whisper` |
| `TN_MODEL` | `base` | See table above |
| `TN_DEVICE` | `auto` | `cpu` / `cuda` / `auto` |
| `TN_COMPUTE_TYPE` | `default` | `int8` (CPU) / `float16` (GPU) when default |
| `TN_DOWNLOAD_ROOT` | `./models` | Weight cache |
| `TN_MAX_BYTES` | `26214400` | 25 MiB upload/path cap |
| `TN_TIMEOUT` | `600` | Per-job ceiling (seconds) |
| `TN_LANGUAGE` | _(empty)_ | Force language; empty = auto |
| `TN_BEAM_SIZE` | `5` | Decoder beam |
| `TN_VAD_FILTER` | `true` | Drop long silences (faster-whisper) |
| `TN_ALLOW_URL_FETCH` | `false` | Enable `audio_url` only on trusted nets |
| `TN_PORT` | `8100` | Compose published port (loopback) |

---

## API

| Endpoint | Purpose |
|---|---|
| `POST /transcribe` | JSON: `audio_path` / `audio_url` / `audio_base64` |
| `POST /transcribe/upload` | Multipart file upload |
| `GET /schemas` | Tool definitions for an LLM `tools` array |
| `GET /health` | Liveness + engine info |

Errors come back in the response body, not as HTTP status codes — the caller
is an agent loop, and "file too large" is a result to reason about, not a
transport failure. Every response carries the same keys whether it succeeded
or failed:

```json
{
  "text": "...",
  "language": "en",
  "language_probability": 0.98,
  "duration": 12.4,
  "segments": [{"id": 0, "start": 0.0, "end": 2.1, "text": "..."}],
  "model": "base",
  "backend": "faster-whisper",
  "task": "transcribe",
  "source": "meeting.m4a",
  "error": null
}
```

---

## Security notes

- **Do not publish the service port without auth.** Anyone who can reach it can
  burn your CPU/GPU on arbitrary audio.
- Compose binds to **loopback** only.
- `TN_ALLOW_URL_FETCH` stays **off** by default. Turning it on without an SSRF
  perimeter makes the service an outbound fetch proxy — do not do that on a
  public host.
- Temporary uploads are written under `TMPDIR` and deleted after each job.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

Whisper weights and faster-whisper are MIT. No third-party STT API required.

Copyright 2026 Lucas D Marshall (Kaung Myat San).
