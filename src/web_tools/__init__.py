"""Self-hosted `web_fetch` / `web_search` tools."""

from .cache import Cache
from .config import CacheConfig, FetchConfig, ProvenanceConfig, SearchConfig
from .fetch import FetchError, FetchResult, web_fetch, web_fetch_sync
from .guard import BlockedURL, Target, check_ip, resolve_target
from .provenance import UrlRegistry, normalize_url
from .search import SearchError, SearchProvider, SearchResult, web_search
from .tools import Toolset, wrap_untrusted

__all__ = [
    "BlockedURL",
    "Cache",
    "CacheConfig",
    "FetchConfig",
    "FetchError",
    "FetchResult",
    "ProvenanceConfig",
    "SearchConfig",
    "SearchError",
    "SearchProvider",
    "SearchResult",
    "Target",
    "Toolset",
    "UrlRegistry",
    "check_ip",
    "normalize_url",
    "resolve_target",
    "web_fetch",
    "web_fetch_sync",
    "web_search",
    "wrap_untrusted",
]

__version__ = "0.1.0"
