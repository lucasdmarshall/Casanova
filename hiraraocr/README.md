<div align="center">

# HiraraOCR

**Self-hosted OCR for AI agents — text, forms/invoices, and handwriting. No API keys.**

Part of the [Hirara](https://github.com/lucasdmarshall/Hirara) tool hub.
Pluggable engines — [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)
(default) and [Tesseract](https://github.com/tesseract-ocr/tesseract) — behind an
OpenCV preprocessing pipeline. URL fetches route through the hub's shared SSRF
guard, [`hirara-core`](../hirara-core/).

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-compatible-8A2BE2.svg)](https://modelcontextprotocol.io/)

</div>

---

## Why

Cloud OCR (Google Vision, Textract, Azure) is accurate — but every document you
send it, you *send it*. OCR inputs are the most sensitive files people have: IDs,
invoices, contracts, medical records, bank statements. HiraraOCR is the opposite
trade: **your documents never leave your machine**, it's free, and the output is
built for agents — clean **markdown**, not a wall of boxes.

It isn't trying to beat Google on raw accuracy. It's trying to be the best
*private, self-hosted, agent-native* OCR — and it wins on things cloud OCR
can't or won't do:

| Lever | What it buys |
|---|---|
| **Preprocessing pipeline** | Deskew, denoise, binarize before recognition — the biggest real accuracy lift, and most wrappers skip it |
| **Agent-native output** | Markdown by default; `detail=layout` adds per-block boxes + confidence |
| **Image *and* scanned PDF** | PDFs are rasterized per page and OCR'd (via poppler) |
| **Pluggable engines** | PaddleOCR (accuracy, 80+ langs) or Tesseract (light) behind one interface — the seam v2 uses to add handwriting/VLM backends |

---

## Three-line proof it helps

On a rendered `Hello HiraraOCR 12345`, PaddleOCR **without** preprocessing read
`Hello Casa0CR 12345` (O→0). **With** the pipeline it read it correctly. That is
the whole pitch in one example: the boring image-cleanup stage is where accuracy
is won or lost.

---

## Quick start

```bash
pip install -e ../hirara-core                 # shared SSRF guard (repo-local)
pip install -e ".[paddle,tesseract,service,mcp]"
```

Tesseract also needs the system binary, and scanned PDFs need poppler:

```bash
apt-get install -y tesseract-ocr poppler-utils
```

As an HTTP service:

```bash
uvicorn hiraraocr.service:app --host 127.0.0.1 --port 8400
```

**Read** an image or scanned PDF (base64, path, or URL) → markdown + text:

```bash
curl -X POST localhost:8400/ocr_read -H 'content-type: application/json' \
  -d '{"file_path":"/path/to/scan.png","languages":["en"]}'
```

Or upload it directly:

```bash
curl -X POST localhost:8400/ocr_read/upload -F file=@receipt.jpg -F languages=en
```

As an MCP server over stdio (Claude Desktop / Cursor / agent runtimes):

```bash
python -m hiraraocr.mcp_server
```

With Docker (loopback-bound; PaddleOCR models download on first use):

```bash
docker compose up -d --build
```

---

## Engines

| Engine | When | Notes |
|---|---|---|
| **`paddleocr`** (default) | Printed text; best accuracy, 80+ languages, boxes + confidence | Pinned to the **2.x** classic API; baked into the Docker image |
| **`tesseract`** | Printed text; lightweight, fast, ubiquitous | Needs the `tesseract-ocr` system binary |
| **`trocr`** | **Handwriting** (v2) | OpenCV line segmentation + a TrOCR model; `pip install 'hiraraocr[handwriting]'`; CPU-runnable but slow. transformers is pinned `<5` |

Override per call with `engine`, or set `COCR_ENGINE`. A GPU/VLM backend slots in
behind the same `OcrEngine` seam for anyone who wants it.

---

## Forms & invoices — `form_extract`

Beyond raw text, `form_extract` pulls **structured data** out of an invoice,
receipt, or form: labelled fields (total, subtotal, tax, invoice number, date)
and a best-effort line-item table. It runs OCR, then extracts by **layout and
pattern** on the resulting blocks — pure Python, CPU-cheap, no second model.

```bash
curl -X POST localhost:8400/form_extract -H 'content-type: application/json' \
  -d '{"file_path":"/path/to/invoice.png","languages":["en"]}'
# → {"fields": {"total": "27.50", "tax": "2.50", "invoice_number": "INV-2026-0042", ...},
#    "table": [["Widget A","2","10.00"], ...]}
```

Pass `templates` to add or override fields for a known layout, e.g.
`{"po_number": ["po #", "purchase order"]}`. It is rule/layout-based — strong on
typical invoices, weaker on unusual layouts (where a GPU VLM, behind the same
seam, does better).

> **Handwriting** uses the `trocr` engine on either tool: `engine="trocr"`.
> It is CPU-runnable but slow — one line at a time — and best on real
> handwriting. GPU users just point torch at CUDA.

---

## API

| Endpoint | Purpose |
|---|---|
| `POST /ocr_read` | OCR one file. `file_path` / `file_url` / `file_base64`, `languages`, `engine`, `preprocess`, `detail` |
| `POST /ocr_read/upload` | Same, multipart file upload |
| `POST /form_extract` | Fields + line-item table. Same sources, plus `templates` |
| `POST /form_extract/upload` | Same, multipart file upload |
| `GET /schemas` | Tool definitions, ready for an LLM `tools` array |
| `GET /health` | Liveness + engine info |

Response carries `text`, `markdown`, `pages[]`, `page_count`, `engine`,
`languages`, `truncated`, `source`, and — with `detail=layout` — `blocks[]`
(text, bbox, confidence). Errors come back in the body, not as HTTP status
codes: the caller is an agent loop, and "could not decode image" is a result to
reason about.

---

## Security

- **`file_url` is off by default.** When enabled (`COCR_ALLOW_URL_FETCH=true`),
  the fetch goes through `hirara-core`'s `safe_download` — resolve-then-pin,
  every redirect hop re-validated, streamed under a byte cap — never a bare
  `httpx.get`.
- **Local file access is gated.** `file_path` lets a caller name any file on the
  host; fine for a local/MCP server, **off in the Docker image**. Set
  `COCR_ALLOW_LOCAL_PATH=true` only for a trusted, local deployment.
- **Everything is size-capped** — input by `COCR_MAX_BYTES`, output text by
  `COCR_MAX_CHARS` (flags `truncated`), PDF pages by `COCR_MAX_PAGES`.

---

## Configuration

All via environment variable.

| Variable | Default | Notes |
|---|---|---|
| `COCR_ENGINE` | `paddleocr` | `paddleocr` or `tesseract` |
| `COCR_LANGUAGES` | `en` | Comma-separated hints, e.g. `en,fr` |
| `COCR_DEVICE` | `cpu` | `cpu` or `gpu` (PaddleOCR / TrOCR) |
| `COCR_TROCR_MODEL` | `microsoft/trocr-base-handwritten` | HuggingFace model for the `trocr` engine |
| `COCR_PREPROCESS` | `true` | Deskew/denoise/binarize before recognition |
| `COCR_MAX_BYTES` | `26214400` | Cap on an input file (25 MB) |
| `COCR_MAX_CHARS` | `500000` | Cap on extracted text; flags `truncated` |
| `COCR_MAX_PAGES` | `50` | Max scanned-PDF pages to OCR |
| `COCR_PDF_DPI` | `200` | PDF rasterization DPI |
| `COCR_ALLOW_URL_FETCH` | `false` | Enable `file_url` (through the SSRF guard) |
| `COCR_ALLOW_LOCAL_PATH` | `true` (lib) / `false` (image) | `file_path` reads |

---

## Testing

```bash
pip install -e ".[dev]"
pytest -q
```

The suite runs against a **fake engine** and a generated PNG, so it needs no
models — it covers reading-order/markdown assembly, source handling, the
language/engine plumbing, size caps, truncation, and that `file_url` routes
through the SSRF guard.

Verified end-to-end on a live CPU server: **Tesseract** and **PaddleOCR 2.10**
read rendered text correctly (and preprocessing measurably improved PaddleOCR's
accuracy); **`form_extract`** pulled every field off a rendered invoice
(`total`/`subtotal` correctly separated); and the **`trocr`** handwriting engine
recognized a line end-to-end on CPU.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

Copyright 2026 Lucas D Marshall (Kaung Myat San).
