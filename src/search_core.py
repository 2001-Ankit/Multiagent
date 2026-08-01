"""Resilient DuckDuckGo wrapper: throttling, retries, and caching.

A swarm can fire dozens of searches per minute, which DuckDuckGo rate-limits. This
module is a drop-in replacement for `ddgs.DDGS` - modules only change their import:

    from src.search_core import DDGS      # instead of: from ddgs import DDGS

It adds:
  - a global minimum interval between real network calls (throttle)
  - retry with exponential backoff on rate-limit / transient failures
  - a short-lived response cache, so parallel agents asking similar questions
    don't each pay for the same query
"""

import os
import threading
import time
from typing import Any

from ddgs import DDGS as _RawDDGS
from ddgs.exceptions import DDGSException

# Minimum seconds between actual outbound searches (across all threads).
SEARCH_MIN_INTERVAL = float(os.getenv("SEARCH_MIN_INTERVAL", "1.2"))
SEARCH_MAX_RETRIES = int(os.getenv("SEARCH_MAX_RETRIES", "3"))
SEARCH_CACHE_TTL = float(os.getenv("SEARCH_CACHE_TTL", "900"))  # 15 minutes

_throttle_lock = threading.Lock()
_last_call_at = 0.0

_cache_lock = threading.Lock()
_cache: dict[tuple, tuple[float, Any]] = {}

_stats = {"calls": 0, "cache_hits": 0, "retries": 0, "failures": 0}


def search_stats() -> dict:
    return dict(_stats)


def _cache_key(method: str, query: str, kwargs: dict) -> tuple:
    return (method, query.strip().lower(), tuple(sorted(kwargs.items())))


def _cache_get(key: tuple):
    with _cache_lock:
        entry = _cache.get(key)
        if not entry:
            return None
        stored_at, value = entry
        if time.time() - stored_at > SEARCH_CACHE_TTL:
            _cache.pop(key, None)
            return None
        return value


def _cache_put(key: tuple, value: Any) -> None:
    with _cache_lock:
        # Keep the cache from growing without bound in a long-running bot.
        if len(_cache) > 400:
            oldest = sorted(_cache.items(), key=lambda kv: kv[1][0])[:100]
            for old_key, _ in oldest:
                _cache.pop(old_key, None)
        _cache[key] = (time.time(), value)


def _wait_turn() -> None:
    """Space out outbound requests so DuckDuckGo doesn't start refusing us."""
    global _last_call_at
    with _throttle_lock:
        elapsed = time.time() - _last_call_at
        if elapsed < SEARCH_MIN_INTERVAL:
            time.sleep(SEARCH_MIN_INTERVAL - elapsed)
        _last_call_at = time.time()


def _looks_rate_limited(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in ("ratelimit", "rate limit", "202", "403", "timeout", "too many")
    )


def _call(method: str, query: str, kwargs: dict) -> Any:
    key = _cache_key(method, query, kwargs)
    cached = _cache_get(key)
    if cached is not None:
        _stats["cache_hits"] += 1
        return cached

    last_error: Exception | None = None
    for attempt in range(SEARCH_MAX_RETRIES):
        _wait_turn()
        try:
            _stats["calls"] += 1
            result = getattr(_RawDDGS(), method)(query=query, **kwargs)
        except DDGSException as exc:
            last_error = exc
            if not _looks_rate_limited(exc) or attempt == SEARCH_MAX_RETRIES - 1:
                break
            _stats["retries"] += 1
            time.sleep(2.0 * (attempt + 1))
            continue
        except Exception as exc:  # network hiccups etc.
            last_error = exc
            if attempt == SEARCH_MAX_RETRIES - 1:
                break
            _stats["retries"] += 1
            time.sleep(1.5 * (attempt + 1))
            continue

        _cache_put(key, result)
        return result

    _stats["failures"] += 1
    # Surface as DDGSException so existing per-tool handlers keep working.
    raise DDGSException(str(last_error) if last_error else "search failed")


class DDGS:
    """Drop-in stand-in for ddgs.DDGS with throttling, retries and caching."""

    def __init__(self, *args, **kwargs) -> None:  # accept the same signature
        self._args = args
        self._kwargs = kwargs

    def text(self, query: str, **kwargs) -> Any:
        return _call("text", query, kwargs)

    def news(self, query: str, **kwargs) -> Any:
        return _call("news", query, kwargs)

    def images(self, query: str, **kwargs) -> Any:
        return _call("images", query, kwargs)

    def videos(self, query: str, **kwargs) -> Any:
        return _call("videos", query, kwargs)

    def books(self, query: str, **kwargs) -> Any:
        return _call("books", query, kwargs)

    def extract(self, url: str, **kwargs) -> Any:
        # extract() takes a url positionally in ddgs; cache it the same way.
        key = _cache_key("extract", url, kwargs)
        cached = _cache_get(key)
        if cached is not None:
            _stats["cache_hits"] += 1
            return cached
        _wait_turn()
        _stats["calls"] += 1
        result = _RawDDGS().extract(url, **kwargs)
        _cache_put(key, result)
        return result
