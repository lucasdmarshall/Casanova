"""In-process tool execution for the hirara SDK.

Most Hirara tools are plain libraries — ``web_fetch``, ``pdf_read``,
``office_read`` and friends do their work in pure Python. When the matching
tool package is installed (``pip install hirara[local]``), the SDK can call it
directly, with no hub and no HTTP hop::

    import hirara
    hirara.pdf_read(path="report.pdf")   # runs in this process, no docker

Discovery is by entry point, not hard-coding. Each tool package advertises an
in-process backend under the ``hirara.backends`` group, pointing at a module
that exposes three names:

    TOOL_NAMES: tuple[str, ...]                 # which tools it serves
    async def call_tool(name, arguments) -> dict
    def tool_schemas() -> list[dict]

So a freshly written tool package joins local mode just by declaring the entry
point — the SDK needs no change. A few tools (``execute_code``, ``web_search``
against your own SearXNG) still need a running service; those simply have no
local backend installed and fall through to the hub.
"""

from __future__ import annotations

import asyncio
from importlib.metadata import entry_points

_GROUP = "hirara.backends"


class LocalBackends:
    """The set of in-process tool backends installed in this environment.

    Discovery is lazy and done once: importing every backend eagerly would drag
    in heavy dependencies the caller may never use.
    """

    def __init__(self) -> None:
        self._routes: dict[str, object] = {}  # tool name -> backend module
        self._modules: list[object] = []
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        for ep in _iter_entry_points(_GROUP):
            try:
                module = ep.load()
                names = getattr(module, "TOOL_NAMES", ())
                if not names or not hasattr(module, "call_tool"):
                    continue
                for name in names:
                    self._routes.setdefault(name, module)
                self._modules.append(module)
            except Exception:
                # A broken or half-installed backend must not take down
                # discovery of the healthy ones.
                continue

    def has(self, name: str) -> bool:
        self._load()
        return name in self._routes

    def names(self) -> list[str]:
        self._load()
        return sorted(self._routes)

    def call(self, name: str, arguments: dict | None) -> dict:
        self._load()
        module = self._routes[name]
        return _run(module.call_tool(name, arguments or {}))

    def schemas(self) -> list[dict]:
        self._load()
        out: list[dict] = []
        for module in self._modules:
            getter = getattr(module, "tool_schemas", None)
            if getter is None:
                continue
            try:
                out.extend(getter())
            except Exception:
                continue
        return out


def _iter_entry_points(group: str):
    """entry_points(group=...) is the modern API; older stdlib returns a dict."""
    try:
        return list(entry_points(group=group))
    except TypeError:  # Python < 3.10 fallback (we require 3.11, but be safe)
        return list(entry_points().get(group, []))


def _run(coro):
    """Drive an async ``call_tool`` from the SDK's synchronous surface.

    The common case — no event loop running — is a plain ``asyncio.run``. If the
    caller is already inside a loop (e.g. a notebook or an async app), we run the
    coroutine on a private loop in a worker thread so we never touch theirs.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro)).result()
