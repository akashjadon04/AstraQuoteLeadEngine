# ============================================================
# net.py — Shared Network Resilience Layer
# Every outbound DDGS (DuckDuckGo) search in the pipeline goes
# through this module so there is exactly ONE global rate limiter,
# ONE timeout policy, and ONE circuit breaker. DDGS scrapes
# duckduckgo.com's HTML (no official API) and rate-limits/blocks
# aggressively — calling it directly and unbounded is what used to
# let the pipeline hang. This module guarantees every call returns
# within a bounded time, and degrades to an empty result instead of
# hanging or raising.
# ============================================================

import asyncio
import time
from typing import Any, Dict, List, Optional

import httpx

import config
from utils.logger import get_logger

logger = get_logger("net")

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


class CircuitBreaker:
    """Opens after N consecutive failures and refuses calls for a cooldown window."""

    def __init__(self, threshold: int, cooldown: float):
        self.threshold = threshold
        self.cooldown = cooldown
        self._consecutive_failures = 0
        self._opened_at: Optional[float] = None

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.time() - self._opened_at >= self.cooldown:
            # Cooldown elapsed — half-open, let the next call probe.
            self._opened_at = None
            self._consecutive_failures = 0
            return False
        return True

    def record_success(self):
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self):
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.threshold and self._opened_at is None:
            self._opened_at = time.time()
            logger.warning(
                f"Circuit breaker OPEN after {self._consecutive_failures} consecutive DDGS "
                f"failures — pausing external searches for {self.cooldown:.0f}s"
            )


def _run_ddgs_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))


class DDGSGate:
    """Global async gate for all DDGS calls: bounded concurrency, paced, timeout-guarded, breaker-protected."""

    def __init__(self):
        # Created lazily, per-event-loop — see _ensure_bound_to_current_loop.
        # This object is a module-level singleton (below) that outlives any
        # single pipeline run, but each "Start Pipeline" click spins up a
        # BRAND NEW event loop in a new thread (dashboard/app.py's
        # run_background_pipeline). asyncio.Semaphore/Lock bind to whichever
        # loop first awaits them — reusing the same instance across two runs
        # crashes with "... is bound to a different event loop" the moment a
        # second run tries to use it. Verified live: the exact crash, on the
        # second "run it again" of a session.
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._pace_lock: Optional[asyncio.Lock] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._last_call = 0.0
        self._breaker = CircuitBreaker(config.NET_CIRCUIT_BREAKER_THRESHOLD, config.NET_CIRCUIT_BREAKER_COOLDOWN)

    def _ensure_bound_to_current_loop(self):
        current_loop = asyncio.get_running_loop()
        if self._loop is not current_loop:
            self._semaphore = asyncio.Semaphore(config.NET_MAX_CONCURRENT_DDGS)
            self._pace_lock = asyncio.Lock()
            self._loop = current_loop

    async def _pace(self):
        async with self._pace_lock:
            now = time.time()
            wait = config.NET_DDGS_MIN_INTERVAL - (now - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.time()

    async def search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Run a DuckDuckGo text search. Always returns a list — never raises, never hangs
        past config.NET_DDGS_TIMEOUT seconds."""
        if self._breaker.is_open():
            return []

        self._ensure_bound_to_current_loop()
        async with self._semaphore:
            await self._pace()
            try:
                results = await asyncio.wait_for(
                    asyncio.to_thread(_run_ddgs_search, query, max_results),
                    timeout=config.NET_DDGS_TIMEOUT,
                )
                self._breaker.record_success()
                return results
            except Exception as e:
                logger.debug(f"DDGS search failed for '{query[:60]}': {e}")
                self._breaker.record_failure()
                return []


# Singleton — shared across every layer so the rate limit/breaker is truly global,
# not per-layer (which is what let five layers each hammer DDGS independently before).
ddgs_gate = DDGSGate()

# One shared, connection-pooled AsyncClient instead of a fresh one per call.
# safe_get() is the general-purpose GET used across Layer 5/6 (website analysis,
# Zefix/SHAB-adjacent fetches) with up to RESEARCH_CONCURRENCY/ENRICH_CONCURRENCY
# leads in flight at once — that many simultaneous fresh clients, each doing its
# own DNS resolution and TLS handshake, is what produced live "getaddrinfo
# failed" bursts under load. Created lazily, per-event-loop (see DDGSGate above
# for why — each pipeline run gets a brand new event loop, and an
# httpx.AsyncClient/asyncio.Lock created for one loop can't be reused once
# that loop is closed and a new run starts a different one).
_async_client: Optional[httpx.AsyncClient] = None
_async_client_lock: Optional[asyncio.Lock] = None
_async_client_loop: Optional[asyncio.AbstractEventLoop] = None


async def _get_async_client() -> httpx.AsyncClient:
    global _async_client, _async_client_lock, _async_client_loop
    current_loop = asyncio.get_running_loop()
    if _async_client_loop is not current_loop:
        # New run, new loop — the previous client/lock belong to a loop that's
        # already closed by now. Drop them and start over for this loop; no
        # cross-loop close attempt (the old loop being gone is exactly why we're
        # here, and closing a client on a loop other than the one it was
        # created on isn't safe either).
        _async_client = None
        _async_client_lock = asyncio.Lock()
        _async_client_loop = current_loop

    if _async_client is None:
        async with _async_client_lock:
            if _async_client is None:
                _async_client = httpx.AsyncClient(verify=False, follow_redirects=True, headers=DEFAULT_HEADERS)
    return _async_client


async def safe_get(url: str, timeout: float = 10.0, headers: Optional[dict] = None) -> Optional[httpx.Response]:
    """httpx GET that never raises — returns None on any failure/timeout instead."""
    try:
        client = await _get_async_client()
        return await client.get(url, timeout=timeout, headers=headers or DEFAULT_HEADERS)
    except Exception as e:
        logger.debug(f"safe_get failed for {url}: {e}")
        return None
