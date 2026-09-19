"""Radar service logic — ported from stitch_backend.domains.community.service.

The plugin owns a copy of the AiApiRadar HTTP-proxy + TTL cache logic so it
can serve the 2 radar commands when installed and healthy.  The original
community domain files stay untouched as the dual-format fallback.

Self-contained: no ``stitch_backend`` imports — the plugin is a separate
process with its own sys.path.  Uses stdlib ``time``/``os`` for cache + env
and ``httpx`` (sync ``Client``) for the upstream proxy (same dep as core).

Synchronous design (unlike the async core): the JSON-RPC loop is sync
(like ``stitch-opencode``), so the HTTP client and cache are sync too.
The in-flight dedup + stale-while-revalidate optimisations from the async
core are not needed here — the plugin is a single-threaded process that
serves one request at a time, so concurrent identical requests cannot
arrive.  The TTL cache (120 s) is preserved so repeated requests don't
hammer the upstream.
"""

# _generated_by: stitch_plugin_tools scaffold v3

from __future__ import annotations

import os
import time
from typing import Any

# ── TTL cache ─────────────────────────────────────────────────────────────────

_RADAR_CACHE: dict[tuple, tuple[float, dict]] = {}
_RADAR_CACHE_TTL: float = 120.0
_RADAR_TIMEOUT: float = 10.0

#: Default upstream URL (same as core ``config.airadadar_api_url``).
_DEFAULT_API_URL = "https://aiapiradar.whitebite.ru"

# Lazily-created singleton HTTP client (sync).  Reused across calls to avoid
# paying the connection-pool / TLS handshake cost on every request.
_HTTP_CLIENT: Any = None


def _get_http_client() -> Any:
    """Return the lazily-created singleton ``httpx.Client``."""
    global _HTTP_CLIENT
    if _HTTP_CLIENT is not None and not _HTTP_CLIENT.is_closed:
        return _HTTP_CLIENT
    import httpx

    _HTTP_CLIENT = httpx.Client(timeout=_RADAR_TIMEOUT)
    return _HTTP_CLIENT


def _radar_get(path: str, params: dict[str, str]) -> dict:
    """GET ``{AIRADAR_API_URL}{path}`` and return the JSON payload.

    Raises ``RuntimeError`` on any transport, HTTP-status, or JSON-decode
    failure (the JSON-RPC loop maps it to a -32603 error).
    """
    base_url = os.environ.get("AIRADAR_API_URL", _DEFAULT_API_URL).rstrip("/")
    url = f"{base_url}{path}"
    client = _get_http_client()
    try:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001 — surface as RuntimeError to RPC loop
        raise RuntimeError(f"AiApiRadar unavailable: {exc}") from exc


def _fetch_cached(cache_key: tuple, path: str, params: dict[str, str]) -> dict:
    """Return cached payload (fresh) or fetch upstream and cache it."""
    entry = _RADAR_CACHE.get(cache_key)
    if entry is not None:
        ts, payload = entry
        if time.monotonic() - ts <= _RADAR_CACHE_TTL:
            return payload
    payload = _radar_get(path, params)
    _RADAR_CACHE[cache_key] = (time.monotonic(), payload)
    return payload


# ── Param validation (ported from RadarOffersParams) ──────────────────────────

_VALID_SORT = {"new", "amount"}
_VALID_EFFORT = {"easy", "medium", "hard"}


def _validate_offers_params(params: dict[str, Any]) -> dict[str, str]:
    """Validate and whitelist query params for ``GET /api/offers``.

    Mirrors ``RadarOffersParams``: ``limit`` clamped to 1..500, ``sort``
    and ``effort`` enum-validated, unknown fields silently dropped.
    """
    # limit (default 50, clamped 1..500)
    limit = params.get("limit", 50)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(500, limit))

    # offset (default 0)
    offset = params.get("offset", 0)
    try:
        offset = int(offset)
    except (TypeError, ValueError):
        offset = 0

    query: dict[str, str] = {"limit": str(limit), "offset": str(offset)}

    sort = params.get("sort")
    if sort and str(sort) in _VALID_SORT:
        query["sort"] = str(sort)

    type_ = params.get("type")
    if type_:
        query["type"] = str(type_)

    effort = params.get("effort")
    if effort and str(effort) in _VALID_EFFORT:
        query["effort"] = str(effort)

    status_ = params.get("status")
    if status_:
        query["status"] = str(status_)

    q = params.get("q")
    if q:
        query["q"] = str(q)

    since_hours = params.get("since_hours")
    if since_hours is not None:
        try:
            since_hours = int(since_hours)
            if since_hours > 0:
                query["since_hours"] = str(since_hours)
        except (TypeError, ValueError):
            pass

    return query


# ── Public command handlers ───────────────────────────────────────────────────


def fetch_radar_offers(params: dict[str, Any]) -> dict:
    """Proxy ``GET /api/offers`` with validated query params + TTL cache."""
    query = _validate_offers_params(params)
    cache_key = ("offers",) + tuple(sorted(query.items()))
    return _fetch_cached(cache_key, "/api/offers", query)


def fetch_radar_stats() -> dict:
    """Proxy ``GET /api/stats`` with TTL cache (no params)."""
    return _fetch_cached(("stats",), "/api/stats", {})


def warm_cache() -> None:
    """Pre-fetch stats + default offers so the first request hits the cache.

    Called from the plugin's init handler (daemon thread — the handshake
    must not block on the upstream).  Failures only leave the cache cold.
    """
    for fetch in (
        lambda: fetch_radar_offers({"limit": 500}),
        fetch_radar_stats,
    ):
        try:
            fetch()
        except Exception:  # noqa: BLE001 — warmup must never surface
            pass
