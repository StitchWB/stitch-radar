"""RPC entry point for the stitch-radar service plugin.

Spawned by ``ServicePluginHost`` as ``python -m stitch_radar``.
Implements the JSON-RPC 2.0 line protocol via ``RpcPluginServer``
(imported from ``autoreg.plugin.rpc`` when available, otherwise from
the vendored ``_vendor/rpc_server.py`` copy).

Protocol methods handled by ``RpcPluginServer``:
  - ``plugin.init``    → stores handshake params (db_path, data_dir).
  - ``plugin.call``    → dispatches to command handlers.
  - ``plugin.ping``    → returns ``"pong"``.
  - ``plugin.shutdown`` → returns ``None`` and exits.

Commands mirror the built-in community radar command names (identity
mapping — no prefix to strip) so the dual-format proxy can route to them
when the plugin is installed and healthy.
"""

# _generated_by: stitch_plugin_tools scaffold v3

from __future__ import annotations

from typing import Any

from . import service

try:
    from autoreg.plugin.rpc import RpcPluginServer
except ImportError:
    from ._vendor.rpc_server import RpcPluginServer


# ── State received in plugin.init handshake ───────────────────────────────


class _Ctx:
    """Mutable container for plugin.init handshake state."""

    db_path: str = ""
    data_dir: str = ""


ctx = _Ctx()


def _handle_init(params: dict[str, Any]) -> dict[str, Any]:
    """Store handshake params and return them as the init result."""
    ctx.db_path = str(params.get("db_path", ""))
    ctx.data_dir = str(params.get("data_dir", ""))
    return {
        "plugin_id": params.get("plugin_id", ""),
        "db_path": ctx.db_path,
        "data_dir": ctx.data_dir,
        # Capability negotiation: no reverse-RPC used.  Declared
        # explicitly for contract uniformity.
        "capabilities": [],
    }


def _handle_migrate_db(params: dict[str, Any]) -> dict[str, Any]:
    """No-op migration (storage.sqlite=false). Returns version ack."""
    return {
        "from_version": params.get("from_version", 0),
        "to_version": params.get("to_version", 1),
    }


# ── Mirrored radar commands ──────────────────────────────────────────────────


def _handle_get_radar_offers(params: dict[str, Any]) -> dict[str, Any]:
    """Proxy AiApiRadar ``GET /api/offers`` (mirrors get_radar_offers)."""
    return service.fetch_radar_offers(params)


def _handle_get_radar_stats(params: dict[str, Any]) -> dict[str, Any]:
    """Proxy AiApiRadar ``GET /api/stats`` (mirrors get_radar_stats)."""
    return service.fetch_radar_stats()


# ── Server entry point ────────────────────────────────────────────────────


def main() -> None:
    """Register handlers and serve the JSON-RPC loop."""
    server = RpcPluginServer()
    server.set_init_handler(_handle_init)
    server.register("_migrate_db", _handle_migrate_db)
    server.register("get_radar_offers", _handle_get_radar_offers)
    server.register("get_radar_stats", _handle_get_radar_stats)
    server.serve()


if __name__ == "__main__":
    main()
